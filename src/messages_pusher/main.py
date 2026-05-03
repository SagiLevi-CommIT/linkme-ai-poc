"""Messages Pusher — high-throughput S3 → SQS streaming for the simulator.

Target: 500,000 messages in 60 seconds ≈ 8,334 msgs/sec aggregate across
all pods. Each pod reads a slice of `batch-*.jsonl` files from S3 and
pushes to the Incoming SQS queue via `send_message_batch` (10 msgs per
call) using a thread pool.

Coordination (partitioning):
    Every pod reads `RUN_ID` + `POD_INDEX` + `POD_COUNT` env vars. The
    full list of batch files under `s3://.../messages/{run_id}/` is
    listed, sorted, then sharded — pod N processes every (N'th)% files.
    This is simple enough to run as a Job with `parallelism: 10` and
    `POD_INDEX` injected via the downward API using env from the pod's
    metadata annotations, or via a hard-coded StatefulSet-style index.

Operational model:
    Designed to be run as a Kubernetes Job with parallelism N. The Job
    exits after all assigned files are drained, making it a natural fit
    for ephemeral simulator runs.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import boto3

from common import config
from common.logging_config import setup_logging
from common.metrics import put_metric


setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("messages_pusher")


# ----------------------------------------------------------------
# Environment config
# ----------------------------------------------------------------

INCOMING_QUEUE_URL = os.environ.get("INCOMING_QUEUE_URL", "")
INPUT_BUCKET = os.environ.get("INPUT_MESSAGES_BUCKET", "")
RUN_ID = os.environ.get("RUN_ID", "")
POD_INDEX = int(os.environ.get("POD_INDEX", "0"))
POD_COUNT = int(os.environ.get("POD_COUNT", "1"))
SEND_WORKERS = int(os.environ.get("SEND_WORKERS", "50"))
S3_PREFIX = os.environ.get("S3_PREFIX", f"messages/{RUN_ID}/" if RUN_ID else "messages/")

if not INCOMING_QUEUE_URL or not INPUT_BUCKET:
    logger.error(
        "Missing required env: INCOMING_QUEUE_URL=%s INPUT_MESSAGES_BUCKET=%s",
        bool(INCOMING_QUEUE_URL),
        bool(INPUT_BUCKET),
    )
    sys.exit(2)

if not RUN_ID:
    RUN_ID = f"adhoc-{int(time.time())}"
    logger.warning("RUN_ID not set, generated %s", RUN_ID)


# ----------------------------------------------------------------
# Clients
# ----------------------------------------------------------------

_s3 = boto3.client("s3", region_name=config.AWS_REGION)
_sqs = boto3.client(
    "sqs",
    region_name=config.AWS_REGION,
    config=boto3.session.Config(
        retries={"max_attempts": 10, "mode": "adaptive"},
        max_pool_connections=SEND_WORKERS * 2,
    ) if hasattr(boto3, "session") else None,
)


# ----------------------------------------------------------------
# S3 helpers
# ----------------------------------------------------------------

def _list_batch_files() -> list[str]:
    """List all batch-*.jsonl files under S3_PREFIX sorted by key."""
    keys: list[str] = []
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=INPUT_BUCKET, Prefix=S3_PREFIX):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if k.endswith(".jsonl"):
                keys.append(k)
    keys.sort()
    return keys


def _pod_slice(keys: list[str]) -> list[str]:
    if POD_COUNT <= 1:
        return keys
    return [k for i, k in enumerate(keys) if i % POD_COUNT == POD_INDEX]


# ----------------------------------------------------------------
# SQS send
# ----------------------------------------------------------------

def _prepare_message_body(line: str) -> str | None:
    """Normalize one JSONL line before it enters the pipeline."""
    body = line.strip().lstrip("\ufeff")
    if not body:
        return None

    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("JSONL record must be an object")

    payload["run_id"] = payload.get("run_id") or RUN_ID
    return json.dumps(payload, separators=(",", ":"))


def _send_batch(lines: list[str]) -> int:
    """Send up to 10 lines in a single SendMessageBatch. Returns # succeeded."""
    if not lines:
        return 0
    entries = []
    for line in lines[:10]:
        try:
            body = _prepare_message_body(line)
        except Exception:
            logger.exception("Invalid JSONL record; skipping")
            put_metric(
                "MessageInvalid",
                1,
                dimensions={"Service": "messages-pusher", "RunId": RUN_ID},
            )
            continue
        if not body:
            continue
        entries.append({"Id": uuid.uuid4().hex, "MessageBody": body})
    if not entries:
        return 0
    try:
        resp = _sqs.send_message_batch(QueueUrl=INCOMING_QUEUE_URL, Entries=entries)
    except Exception:
        logger.exception("SendMessageBatch failed for %d entries", len(entries))
        put_metric(
            "SendBatchFailed",
            1,
            dimensions={"Service": "messages-pusher"},
        )
        return 0

    failed = resp.get("Failed", [])
    if failed:
        put_metric(
            "SendBatchPartialFailure",
            len(failed),
            dimensions={"Service": "messages-pusher"},
        )
    return len(entries) - len(failed)


def _process_file(key: str) -> int:
    """Stream a single JSONL file and push every line to SQS. Returns #messages sent."""
    t0 = time.perf_counter()
    sent = 0

    obj = _s3.get_object(Bucket=INPUT_BUCKET, Key=key)
    body_iter = obj["Body"].iter_lines(chunk_size=1024 * 1024)

    buffer: list[str] = []
    futures: list[concurrent.futures.Future] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=SEND_WORKERS) as pool:
        for raw in body_iter:
            if not raw:
                continue
            if isinstance(raw, bytes):
                line = raw.decode("utf-8", errors="replace")
            else:
                line = raw
            buffer.append(line)
            if len(buffer) >= 10:
                futures.append(pool.submit(_send_batch, buffer))
                buffer = []

        if buffer:
            futures.append(pool.submit(_send_batch, buffer))

        for f in concurrent.futures.as_completed(futures):
            try:
                sent += f.result()
            except Exception:
                logger.exception("send_batch future failed")

    elapsed = time.perf_counter() - t0
    rate = sent / elapsed if elapsed > 0 else 0.0
    logger.info(
        "Pushed %d messages from %s in %.2fs (%.0f msg/s)",
        sent,
        key,
        elapsed,
        rate,
    )
    put_metric(
        "MessagesPushed",
        sent,
        dimensions={"Service": "messages-pusher", "RunId": RUN_ID},
    )
    put_metric(
        "PushLatencyMs",
        elapsed * 1000,
        unit="Milliseconds",
        dimensions={"Service": "messages-pusher"},
    )
    return sent


def main() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    logger.info(
        "Messages pusher starting: run_id=%s pod=%d/%d bucket=%s prefix=%s queue=%s workers=%d started_at=%s",
        RUN_ID,
        POD_INDEX,
        POD_COUNT,
        INPUT_BUCKET,
        S3_PREFIX,
        INCOMING_QUEUE_URL,
        SEND_WORKERS,
        started_at,
    )

    all_keys = _list_batch_files()
    my_keys = _pod_slice(all_keys)
    logger.info(
        "Discovered %d total batch files; this pod will process %d",
        len(all_keys),
        len(my_keys),
    )

    if not my_keys:
        logger.warning("No batch files for this pod; exiting")
        return 0

    total_sent = 0
    t0 = time.perf_counter()
    for key in my_keys:
        try:
            total_sent += _process_file(key)
        except Exception:
            logger.exception("Failed to process %s", key)

    elapsed = time.perf_counter() - t0
    rate = total_sent / elapsed if elapsed > 0 else 0.0
    logger.info(
        "Pusher finished: run_id=%s pod=%d/%d sent=%d elapsed=%.2fs rate=%.0f msg/s",
        RUN_ID,
        POD_INDEX,
        POD_COUNT,
        total_sent,
        elapsed,
        rate,
    )
    put_metric(
        "PodTotalMessages",
        total_sent,
        dimensions={"Service": "messages-pusher", "RunId": RUN_ID, "Pod": str(POD_INDEX)},
    )
    put_metric(
        "PodThroughputMsgPerSec",
        rate,
        unit="Count/Second",
        dimensions={"Service": "messages-pusher", "RunId": RUN_ID},
    )
    summary = {
        "event": "pusher_complete",
        "run_id": RUN_ID,
        "pod_index": POD_INDEX,
        "pod_count": POD_COUNT,
        "messages_sent": total_sent,
        "elapsed_seconds": round(elapsed, 2),
        "rate_msg_per_sec": round(rate, 2),
    }
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
