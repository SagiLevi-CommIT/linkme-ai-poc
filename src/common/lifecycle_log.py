"""Single-line JSON lifecycle logs for PoC reporting (CloudWatch Logs).

Emits ``message.lifecycle`` to the log group named by ``MESSAGE_LIFECYCLE_LOG_GROUP``
(default ``/linkme/poc/message-lifecycle``) via ``logs:PutLogEvents``. Uses one log
stream per process and a lock so sequence tokens stay valid under concurrency.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import sys
import threading
import time
from typing import Any

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_STREAM_ENSURED = False
_SEQUENCE_TOKEN: str | None = None


def _lifecycle_log_group() -> str:
    """Resolve log group at call time so empty ECS env (\"\") does not override the default."""
    raw = os.environ.get("MESSAGE_LIFECYCLE_LOG_GROUP")
    if raw is None or not str(raw).strip():
        return "/linkme/poc/message-lifecycle"
    return str(raw).strip()


def _lifecycle_log_stream() -> str:
    raw = os.environ.get("MESSAGE_LIFECYCLE_LOG_STREAM")
    if raw is not None and str(raw).strip():
        base = str(raw).strip()
    else:
        base = f"lifecycle-{socket.gethostname()}-{os.getpid()}"
    # CloudWatch allows : / * etc.; keep names short and safe for IAM/stream APIs.
    safe = re.sub(r"[^a-zA-Z0-9_.\-/]", "-", base).strip("-")
    return (safe or "lifecycle-default")[:512]


def _client():  # type: ignore[no-untyped-def]
    import boto3

    from common import config

    return boto3.client("logs", region_name=config.AWS_REGION)


def emit_message_lifecycle(payload: dict[str, Any]) -> None:
    """Write one compact JSON line to the lifecycle log group (best-effort)."""
    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(line) > 256_000:
        logger.warning("message.lifecycle line exceeds CW limit; truncating metadata")
        line = json.dumps(
            {k: payload.get(k) for k in ("event", "message_id", "creator_id", "status", "error_stage")},
            separators=(",", ":"),
        )

    ts_ms = int(time.time() * 1000)
    global _STREAM_ENSURED, _SEQUENCE_TOKEN
    log_group = _lifecycle_log_group()
    log_stream = _lifecycle_log_stream()
    try:
        with _LOCK:
            c = _client()
            if not _STREAM_ENSURED:
                try:
                    c.create_log_stream(logGroupName=log_group, logStreamName=log_stream)
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code != "ResourceAlreadyExistsException":
                        raise
                _STREAM_ENSURED = True
            kwargs: dict[str, Any] = {
                "logGroupName": log_group,
                "logStreamName": log_stream,
                "logEvents": [{"timestamp": ts_ms, "message": line}],
            }
            if _SEQUENCE_TOKEN is not None:
                kwargs["sequenceToken"] = _SEQUENCE_TOKEN
            try:
                resp = c.put_log_events(**kwargs)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in ("InvalidSequenceTokenException", "DataAlreadyAcceptedException"):
                    raise
                streams = c.describe_log_streams(
                    logGroupName=log_group,
                    logStreamNamePrefix=log_stream,
                    limit=50,
                )
                for s in streams.get("logStreams", []):
                    if s.get("logStreamName") == log_stream:
                        _SEQUENCE_TOKEN = s.get("uploadSequenceToken")
                        break
                kwargs["sequenceToken"] = _SEQUENCE_TOKEN
                resp = c.put_log_events(**kwargs)
            _SEQUENCE_TOKEN = resp.get("nextSequenceToken")
    except Exception as exc:
        logger.exception(
            "Failed to emit message.lifecycle group=%s stream=%s message_id=%s err=%s",
            log_group,
            log_stream,
            payload.get("message_id"),
            exc,
        )
        print(
            f"[lifecycle_log] FAILED group={log_group!r} stream={log_stream!r} "
            f"message_id={payload.get('message_id')!r}: {exc}",
            file=sys.stderr,
            flush=True,
        )
