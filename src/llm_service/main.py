"""LLM Service — long-running SQS FIFO consumer on EKS.

Consumes BatchQueueItems off the AI Processing FIFO queue. Each FIFO
`MessageGroupId` is a `lead_id`, so items for the same creator are
processed in order; different creators parallelize across message
groups and across replicas.

Per received batch:
  1. Load the creator profile once.
  2. Split into borderline vs full-miss items.
  3. For full-miss: retrieve KB context once, then batched LLM call.
  4. For borderline: batched lightweight adaptation call.
  5. Write each answer to DynamoDB Results.
  6. Write back to exact cache (DDB) + semantic cache (MemoryDB) so
     future identical / similar questions are hits.
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
    BatchQuestion,
    CacheTier,
    MissType,
)
from common.schema import CreatorProfile

from batch_llm.batch_prompt_builder import build_batch_prompt
from batch_llm.batch_response_parser import parse_batch_response
from batch_llm.bedrock_client import invoke_llm
from batch_llm.embedding_router import load_centroids, route_batch
from batch_llm.kb_client import retrieve_context
from batch_llm.prompt_builder import build_system_prompt


setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("llm_service")
load_centroids()


# ----------------------------------------------------------------
# Environment-driven runtime configuration
# ----------------------------------------------------------------

AI_PROCESSING_QUEUE_URL = os.environ.get("AI_PROCESSING_QUEUE_URL", "")
RESULTS_TABLE = os.environ.get("RESULTS_TABLE", "")
RUN_ID = os.environ.get("RUN_ID", "")
WORKER_COUNT = int(os.environ.get("WORKER_COUNT", "10"))
POLL_MAX_MESSAGES = int(os.environ.get("POLL_MAX_MESSAGES", "10"))
POLL_WAIT_SECONDS = int(os.environ.get("POLL_WAIT_SECONDS", "20"))

if not AI_PROCESSING_QUEUE_URL or not RESULTS_TABLE:
    logger.error(
        "Missing required env: AI_PROCESSING_QUEUE_URL=%s RESULTS_TABLE=%s",
        bool(AI_PROCESSING_QUEUE_URL),
        bool(RESULTS_TABLE),
    )
    sys.exit(2)


# ----------------------------------------------------------------
# Shared AWS clients
# ----------------------------------------------------------------

_sqs = boto3.client("sqs", region_name=config.AWS_REGION)
_ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
_results_table = _ddb.Table(RESULTS_TABLE)


_stop_event = threading.Event()


def _install_signal_handlers() -> None:
    def _handle(signum: int, _frame: object) -> None:
        logger.info("Received signal %s, draining workers and exiting", signum)
        _stop_event.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


# ----------------------------------------------------------------
# Batch processing
# ----------------------------------------------------------------

def _chunk(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _item_run_id(item: BatchQueueItem) -> str:
    return item.run_id or RUN_ID or "adhoc"


def _process_batch(items: list[BatchQueueItem]) -> None:
    """Process a batch of BatchQueueItems all sharing the same lead_id."""
    if not items:
        return

    lead_id = items[0].lead_id
    set_correlation_id(items[0].correlation_id)

    profile = _load_profile(lead_id)
    if not profile:
        logger.error("No profile for lead=%s; emitting error results for %d items", lead_id, len(items))
        for item in items:
            _write_result(
                item=item,
                answer="",
                source="profile_missing",
                model_used="none",
                cache_tier=CacheTier.FULL_MISS,
                latency_ms=0,
            )
        return

    max_size = config.BATCH_MAX_SIZE
    borderline = [i for i in items if i.miss_type == MissType.BORDERLINE]
    full_miss = [i for i in items if i.miss_type == MissType.FULL_MISS]

    for chunk in _chunk(borderline, max_size):
        _process_borderline(chunk, profile)
    for chunk in _chunk(full_miss, max_size):
        _process_full_miss(chunk, profile, lead_id)


def _process_borderline(items: list[BatchQueueItem], profile: CreatorProfile) -> None:
    t0 = time.perf_counter()
    system_prompt = build_system_prompt(profile)
    questions = [
        BatchQuestion(id=item.message_id, text=item.question_text)
        for item in items
    ]

    prompt = build_batch_prompt(system_prompt, questions)
    model = "haiku"
    raw = invoke_llm(prompt, model=model)

    parsed = parse_batch_response(raw, [q.id for q in questions])
    latency_ms = (time.perf_counter() - t0) * 1000
    put_metric(
        "LLMBatchLatencyMs",
        latency_ms,
        unit="Milliseconds",
        dimensions={"Service": "llm-service", "Type": "borderline", "Model": model, "RunId": _item_run_id(items[0])},
    )

    if parsed:
        answer_map = {a.id: a.answer for a in parsed.answers}
        for item in items:
            answer = answer_map.get(item.message_id, "")
            if answer:
                _write_result(
                    item=item,
                    answer=answer,
                    source="borderline_adapt",
                    model_used=model,
                    cache_tier=CacheTier.SEMANTIC_BORDERLINE,
                    latency_ms=latency_ms / max(len(items), 1),
                )
                _write_back_to_caches(item, answer)
            else:
                _fallback_individual(item, profile, model)
    else:
        put_metric("BatchParseFailed", 1, dimensions={"Service": "llm-service", "Type": "borderline"})
        for item in items:
            _fallback_individual(item, profile, model)


def _process_full_miss(items: list[BatchQueueItem], profile: CreatorProfile, lead_id: str) -> None:
    t0 = time.perf_counter()
    combined_query = " ".join(i.question_text for i in items[:3])
    kb_chunks = retrieve_context(combined_query, lead_id)

    system_prompt = build_system_prompt(profile, kb_chunks=kb_chunks)
    questions = [
        BatchQuestion(id=item.message_id, text=item.question_text)
        for item in items
    ]

    embeddings = [item.embedding_vector for item in items]
    model = route_batch(embeddings)
    put_metric(
        "ModelRouting",
        1,
        dimensions={"Service": "llm-service", "Model": model, "RunId": _item_run_id(items[0])},
    )

    prompt = build_batch_prompt(system_prompt, questions)
    raw = invoke_llm(prompt, model=model)

    parsed = parse_batch_response(raw, [q.id for q in questions])
    latency_ms = (time.perf_counter() - t0) * 1000
    put_metric(
        "LLMBatchLatencyMs",
        latency_ms,
        unit="Milliseconds",
        dimensions={"Service": "llm-service", "Type": "full_miss", "Model": model, "RunId": _item_run_id(items[0])},
    )

    source = f"llm_{model}"
    if parsed:
        answer_map = {a.id: a.answer for a in parsed.answers}
        for item in items:
            answer = answer_map.get(item.message_id, "")
            if answer:
                _write_result(
                    item=item,
                    answer=answer,
                    source=source,
                    model_used=model,
                    cache_tier=CacheTier.FULL_MISS,
                    latency_ms=latency_ms / max(len(items), 1),
                )
                _write_back_to_caches(item, answer)
            else:
                _fallback_individual(item, profile, model, kb_chunks)
    else:
        put_metric("BatchParseFailed", 1, dimensions={"Service": "llm-service", "Type": "full_miss"})
        for item in items:
            _fallback_individual(item, profile, model, kb_chunks)


def _fallback_individual(
    item: BatchQueueItem,
    profile: CreatorProfile,
    model: str,
    kb_chunks: str = "",
) -> None:
    logger.warning("Falling back to individual LLM call for %s", item.message_id)
    put_metric("BatchFallbackIndividual", 1, dimensions={"Service": "llm-service", "RunId": _item_run_id(item)})
    t0 = time.perf_counter()
    system_prompt = build_system_prompt(profile, kb_chunks=kb_chunks)
    prompt = f"{system_prompt}\n\nUSER MESSAGE:\n{item.question_text}"
    answer = invoke_llm(prompt, model=model)  # type: ignore[arg-type]
    latency_ms = (time.perf_counter() - t0) * 1000
    cache_tier = (
        CacheTier.SEMANTIC_BORDERLINE
        if item.miss_type == MissType.BORDERLINE
        else CacheTier.FULL_MISS
    )
    _write_result(
        item=item,
        answer=answer,
        source=f"llm_{model}_fallback",
        model_used=model,
        cache_tier=cache_tier,
        latency_ms=latency_ms,
    )
    _write_back_to_caches(item, answer)


# ----------------------------------------------------------------
# Writers
# ----------------------------------------------------------------

def _write_result(
    *,
    item: BatchQueueItem,
    answer: str,
    source: str,
    model_used: str,
    cache_tier: CacheTier,
    latency_ms: float,
) -> None:
    ddb_item: dict[str, Any] = {
        "message_id": item.message_id,
        "run_id": _item_run_id(item),
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "lead_id": item.lead_id,
        "question": item.question_text,
        "answer": answer,
        "source": source,
        "model_used": model_used,
        "cache_tier": cache_tier.value,
        "latency_ms": int(latency_ms),
        "tenant_id": item.lead_id,
        "correlation_id": item.correlation_id,
    }
    if item.similarity_score:
        ddb_item["similarity_score"] = decimal_from_float(item.similarity_score)

    _results_table.put_item(Item=ddb_item)

    put_metric(
        "EndToEndLatencyMs",
        latency_ms,
        unit="Milliseconds",
        dimensions={"Service": "llm-service", "Source": source, "RunId": _item_run_id(item)},
    )


def _write_back_to_caches(item: BatchQueueItem, answer: str) -> None:
    """Update exact + semantic caches so future identical/similar questions hit."""
    try:
        # Late import to avoid pulling redis/boto deps during unit tests
        from cache_processor.semantic_cache import (
            write_to_cache,
        )

        write_to_cache(
            item.lead_id,
            item.question_text,
            answer,
            item.embedding_vector,
            run_id=_item_run_id(item),
            seed_source="simulator_runtime" if _item_run_id(item) != "adhoc" else "",
        )
    except Exception:
        logger.warning("write_to_cache (exact+semantic) failed for %s", item.message_id, exc_info=True)

    try:
        from cache_processor.vector_cache import write_semantic_cache
        from cache_processor.semantic_cache import (
            normalize_question,
            question_hash,
        )

        q_hash = question_hash(normalize_question(item.question_text))
        write_semantic_cache(
            item.lead_id,
            item.question_text,
            answer,
            item.embedding_vector,
            q_hash,
        )
    except Exception:
        logger.debug("Vector cache write (DDB fallback path) skipped", exc_info=True)


def _load_profile(lead_id: str) -> CreatorProfile | None:
    table_name = os.environ.get("PROFILES_TABLE", config.PROFILES_TABLE)
    table = _ddb.Table(table_name)
    try:
        resp = table.get_item(Key={"tenant_id": lead_id})
    except Exception:
        logger.exception("DynamoDB GetItem profile failed for lead=%s", lead_id)
        return None
    row = resp.get("Item")
    if not row:
        return None
    try:
        profile_data = row.get("profile", {})
        if isinstance(profile_data, str):
            profile_data = json.loads(profile_data)
        return CreatorProfile(**profile_data)
    except Exception:
        logger.exception("Invalid profile row for lead=%s", lead_id)
        return None


# ----------------------------------------------------------------
# Worker loop
# ----------------------------------------------------------------

def _worker(worker_id: int) -> None:
    logger.info("LLM-service worker %d started", worker_id)
    while not _stop_event.is_set():
        try:
            resp = _sqs.receive_message(
                QueueUrl=AI_PROCESSING_QUEUE_URL,
                MaxNumberOfMessages=POLL_MAX_MESSAGES,
                WaitTimeSeconds=POLL_WAIT_SECONDS,
                VisibilityTimeout=300,
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

        # Group by MessageGroupId so we process each lead's batch atomically.
        by_group: dict[str, list[dict]] = {}
        for record in records:
            group_id = record.get("Attributes", {}).get("MessageGroupId", "__none__")
            by_group.setdefault(group_id, []).append(record)

        for group_records in by_group.values():
            items: list[BatchQueueItem] = []
            entries_to_delete: list[dict[str, str]] = []
            try:
                for record in group_records:
                    body = json.loads(record["Body"])
                    items.append(BatchQueueItem(**body))
                _process_batch(items)
                for record in group_records:
                    entries_to_delete.append(
                        {
                            "Id": record["MessageId"],
                            "ReceiptHandle": record["ReceiptHandle"],
                        }
                    )
                put_metric(
                    "BatchProcessed",
                    1,
                    dimensions={
                        "Service": "llm-service",
                        "BatchSize": str(len(items)),
                        "RunId": _item_run_id(items[0]) if items else RUN_ID or "adhoc",
                    },
                )
            except Exception:
                logger.exception(
                    "Batch processing failed for group=%s size=%d",
                    group_records[0].get("Attributes", {}).get("MessageGroupId"),
                    len(group_records),
                )
                put_metric("BatchFailed", 1, dimensions={"Service": "llm-service"})

            if entries_to_delete:
                try:
                    _sqs.delete_message_batch(
                        QueueUrl=AI_PROCESSING_QUEUE_URL,
                        Entries=entries_to_delete,
                    )
                except Exception:
                    logger.exception("delete_message_batch failed")

    logger.info("LLM-service worker %d drained", worker_id)


def main() -> int:
    logger.info(
        "LLM service starting: workers=%d region=%s ai_processing=%s results=%s",
        WORKER_COUNT,
        config.AWS_REGION,
        AI_PROCESSING_QUEUE_URL,
        RESULTS_TABLE,
    )
    _install_signal_handlers()

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
        futures = [pool.submit(_worker, i) for i in range(WORKER_COUNT)]
        try:
            for f in concurrent.futures.as_completed(futures):
                f.result()
        except Exception:
            logger.exception("Worker pool terminated with an exception")
            _stop_event.set()
            return 1

    logger.info("LLM service exited cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
