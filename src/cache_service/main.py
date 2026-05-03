"""Cache Service — long-running SQS consumer on EKS.

Reads IncomingMessages from the Incoming SQS queue, performs the three-tier
cache lookup (exact → DDB, semantic → MemoryDB HNSW), and:

  * CACHE HIT  → writes the final answer to the Results DynamoDB table.
  * CACHE MISS → publishes a BatchQueueItem to the AI Processing FIFO queue
                 (MessageGroupId = lead_id so per-creator ordering is preserved).

Runs as a pool of thread workers (default 20). Each worker performs a
long-polling ReceiveMessage (WaitTimeSeconds=20, MaxNumberOfMessages=10)
and processes the batch in-line. On failure the message goes back to the
visibility-timeout window and eventually lands in the DLQ after
`maxReceiveCount` retries (handled by SQS itself).
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3

from common import config
from common.correlation import set_correlation_id
from common.dynamodb_types import decimal_from_float
from common.logging_config import setup_logging
from common.metrics import put_metric
from common.models import (
    BatchQueueItem,
    CacheTier,
    IncomingMessage,
    MissType,
)

from cache_processor.cache_behavior import (
    should_return_immediately,
    should_send_to_batch_queue,
)
from cache_processor.semantic_cache import (
    check_exact_match,
    normalize_question,
    question_hash,
)

# Select embedding + semantic backends at import time the same way the
# existing Lambda handler does.
if config.MEMORYDB_ENDPOINT:
    from cache_processor.semantic_cache import search_vector as search_semantic
else:
    from cache_processor.vector_cache import search_semantic  # type: ignore

if config.SAGEMAKER_ENDPOINT_NAME:
    from cache_processor.embedding_client import embed_text, embed_batch
else:
    from cache_processor.titan_embedding_client import embed_text  # type: ignore

    def embed_batch(texts):  # type: ignore[no-redef]
        return [embed_text(t) for t in texts]


setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("cache_service")


# ----------------------------------------------------------------
# Environment-driven runtime configuration
# ----------------------------------------------------------------

INCOMING_QUEUE_URL = os.environ.get("INCOMING_QUEUE_URL", "")
AI_PROCESSING_QUEUE_URL = os.environ.get("AI_PROCESSING_QUEUE_URL", "")
RESULTS_TABLE = os.environ.get("RESULTS_TABLE", "")
RUN_ID = os.environ.get("RUN_ID", "")  # Injected per simulator run
WORKER_COUNT = int(os.environ.get("WORKER_COUNT", "20"))
POLL_MAX_MESSAGES = int(os.environ.get("POLL_MAX_MESSAGES", "10"))
POLL_WAIT_SECONDS = int(os.environ.get("POLL_WAIT_SECONDS", "20"))

if not INCOMING_QUEUE_URL or not AI_PROCESSING_QUEUE_URL or not RESULTS_TABLE:
    logger.error(
        "Missing required env: INCOMING_QUEUE_URL=%s AI_PROCESSING_QUEUE_URL=%s RESULTS_TABLE=%s",
        bool(INCOMING_QUEUE_URL),
        bool(AI_PROCESSING_QUEUE_URL),
        bool(RESULTS_TABLE),
    )
    sys.exit(2)


# ----------------------------------------------------------------
# Shared AWS clients (thread-safe)
# ----------------------------------------------------------------

_sqs = boto3.client("sqs", region_name=config.AWS_REGION)
_ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
_results_table = _ddb.Table(RESULTS_TABLE)


# ----------------------------------------------------------------
# Graceful shutdown
# ----------------------------------------------------------------

_stop_event = threading.Event()


def _install_signal_handlers() -> None:
    def _handle(signum: int, _frame: object) -> None:
        logger.info("Received signal %s, draining workers and exiting", signum)
        _stop_event.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


# ----------------------------------------------------------------
# Core processing
# ----------------------------------------------------------------

def _process_single(msg: IncomingMessage, embedding: list[float] | None = None) -> None:
    """Process one message. If `embedding` is provided (pre-computed by the
    worker's batch call) we skip the per-message SageMaker invoke.
    """
    correlation_id = msg.correlation_id or msg.message_id
    set_correlation_id(correlation_id)
    t0 = time.perf_counter()

    normalized = normalize_question(msg.question_text)
    q_hash = question_hash(normalized)

    exact = check_exact_match(msg.lead_id, q_hash)
    if exact and should_return_immediately(exact.tier):
        _write_result(
            msg=msg,
            answer=exact.cached_answer or "",
            source="exact_cache",
            model_used="cache",
            cache_tier=CacheTier.EXACT_HIT,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
        put_metric(
            "CacheHit",
            1,
            dimensions={"Tier": "exact", "Service": "cache-service", "RunId": _message_run_id(msg)},
        )
        return

    # Semantic vector search — reuse pre-computed embedding when the worker
    # has batched it, otherwise fall back to a single invoke.
    if embedding is None:
        embedding = embed_text(msg.question_text)
    vec = search_semantic(msg.lead_id, embedding)

    if should_return_immediately(vec.tier):
        _write_result(
            msg=msg,
            answer=vec.cached_answer or "",
            source="semantic_cache",
            model_used="cache",
            cache_tier=CacheTier.SEMANTIC_HIGH_HIT,
            latency_ms=(time.perf_counter() - t0) * 1000,
            similarity_score=vec.similarity_score,
        )
        put_metric(
            "CacheHit",
            1,
            dimensions={"Tier": "semantic_high", "Service": "cache-service", "RunId": _message_run_id(msg)},
        )
        return

    if should_send_to_batch_queue(vec.tier):
        miss_type = (
            MissType.BORDERLINE
            if vec.tier == CacheTier.SEMANTIC_BORDERLINE
            else MissType.FULL_MISS
        )
        item = BatchQueueItem(
            message_id=msg.message_id,
            lead_id=msg.lead_id,
            question_text=msg.question_text,
            embedding_vector=embedding,
            miss_type=miss_type,
            similarity_score=vec.similarity_score,
            correlation_id=correlation_id,
            run_id=_message_run_id(msg),
            cached_question=vec.cached_question,
            cached_answer=vec.cached_answer,
        )
        _publish_to_ai_processing(item)
        put_metric(
            "CacheMiss",
            1,
            dimensions={"Tier": miss_type.value, "Service": "cache-service", "RunId": _message_run_id(msg)},
        )
        return

    # FULL_MISS that the classifier didn't flag for LLM — emit a dead result
    # rather than silently drop it. Shouldn't happen in practice.
    logger.warning(
        "Unhandled cache tier %s for message %s",
        vec.tier,
        msg.message_id,
    )


def _message_run_id(msg: IncomingMessage) -> str:
    return msg.run_id or RUN_ID or "adhoc"


def _write_result(
    *,
    msg: IncomingMessage,
    answer: str,
    source: str,
    model_used: str,
    cache_tier: CacheTier,
    latency_ms: float,
    similarity_score: float | None = None,
) -> None:
    item: dict[str, Any] = {
        "message_id": msg.message_id,
        "run_id": _message_run_id(msg),
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "lead_id": msg.lead_id,
        "question": msg.question_text,
        "answer": answer,
        "source": source,
        "model_used": model_used,
        "cache_tier": cache_tier.value,
        "latency_ms": int(latency_ms),
        "tenant_id": msg.lead_id,
        "correlation_id": msg.correlation_id or msg.message_id,
    }
    if similarity_score is not None:
        item["similarity_score"] = decimal_from_float(similarity_score)

    _results_table.put_item(Item=item)

    put_metric(
        "EndToEndLatencyMs",
        latency_ms,
        unit="Milliseconds",
        dimensions={"Service": "cache-service", "Source": source, "RunId": _message_run_id(msg)},
    )


def _publish_to_ai_processing(item: BatchQueueItem) -> None:
    _sqs.send_message(
        QueueUrl=AI_PROCESSING_QUEUE_URL,
        MessageBody=item.model_dump_json(),
        MessageGroupId=item.lead_id,
        MessageDeduplicationId=item.message_id or str(uuid.uuid4()),
    )


# ----------------------------------------------------------------
# Worker loop
# ----------------------------------------------------------------

def _worker(worker_id: int) -> None:
    logger.info("Cache-service worker %d started", worker_id)
    while not _stop_event.is_set():
        try:
            resp = _sqs.receive_message(
                QueueUrl=INCOMING_QUEUE_URL,
                MaxNumberOfMessages=POLL_MAX_MESSAGES,
                WaitTimeSeconds=POLL_WAIT_SECONDS,
                VisibilityTimeout=60,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )
        except Exception:
            logger.exception("ReceiveMessage failed; backing off 2s")
            time.sleep(2)
            continue

        records = resp.get("Messages", [])
        if not records:
            continue

        # Parse all records up front so we can collapse the SageMaker embed
        # call into one batched invoke. This is the single biggest lever for
        # hitting the 500K/20min target — 10 msgs/worker × 60 workers × 1 call
        # per batch gives the embedding endpoint a real batch size to chew on.
        parsed: list[tuple[dict, IncomingMessage]] = []
        for record in records:
            try:
                body = json.loads(record["Body"])
                msg = IncomingMessage(**body)
                parsed.append((record, msg))
            except Exception:
                logger.exception(
                    "Failed to parse message %s",
                    record.get("MessageId"),
                )
                put_metric(
                    "MessageFailed",
                    1,
                    dimensions={"Service": "cache-service"},
                )

        # One SageMaker invoke for the whole batch.
        embeddings: list[list[float]] | list[None] = [None] * len(parsed)
        if parsed:
            try:
                embeddings = embed_batch([msg.question_text for _, msg in parsed])
            except Exception:
                logger.exception(
                    "embed_batch failed; falling back to per-message embed in _process_single"
                )
                embeddings = [None] * len(parsed)

        entries_to_delete: list[dict[str, str]] = []
        for (record, msg), emb in zip(parsed, embeddings):
            try:
                _process_single(msg, embedding=emb)
                entries_to_delete.append(
                    {
                        "Id": record["MessageId"],
                        "ReceiptHandle": record["ReceiptHandle"],
                    }
                )
                put_metric(
                    "MessageProcessed",
                    1,
                    dimensions={"Service": "cache-service", "RunId": _message_run_id(msg)},
                )
            except Exception:
                logger.exception(
                    "Failed to process message %s",
                    record.get("MessageId"),
                )
                put_metric(
                    "MessageFailed",
                    1,
                    dimensions={"Service": "cache-service"},
                )

        if entries_to_delete:
            try:
                _sqs.delete_message_batch(
                    QueueUrl=INCOMING_QUEUE_URL,
                    Entries=entries_to_delete,
                )
            except Exception:
                logger.exception("delete_message_batch failed")

    logger.info("Cache-service worker %d drained", worker_id)


def main() -> int:
    logger.info(
        "Cache service starting: workers=%d region=%s incoming=%s ai_processing=%s results=%s",
        WORKER_COUNT,
        config.AWS_REGION,
        INCOMING_QUEUE_URL,
        AI_PROCESSING_QUEUE_URL,
        RESULTS_TABLE,
    )
    _install_signal_handlers()

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
        futures = [pool.submit(_worker, i) for i in range(WORKER_COUNT)]
        try:
            for f in concurrent.futures.as_completed(futures):
                # Surface unexpected worker failures so the pod restarts
                f.result()
        except Exception:
            logger.exception("Worker pool terminated with an exception")
            _stop_event.set()
            return 1

    logger.info("Cache service exited cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
