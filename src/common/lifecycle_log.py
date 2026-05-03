"""Single-line JSON lifecycle logs for PoC reporting (CloudWatch Logs).

Emits ``message.lifecycle`` to the log group named by ``MESSAGE_LIFECYCLE_LOG_GROUP``
(default ``/linkme/poc/message-lifecycle``) via ``logs:PutLogEvents``. Uses one log
stream per process and a lock so sequence tokens stay valid under concurrency.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_STREAM_ENSURED = False
_SEQUENCE_TOKEN: str | None = None
_LOG_GROUP = os.environ.get("MESSAGE_LIFECYCLE_LOG_GROUP", "/linkme/poc/message-lifecycle")
_LOG_STREAM = os.environ.get(
    "MESSAGE_LIFECYCLE_LOG_STREAM",
    f"lifecycle-{socket.gethostname()}-{os.getpid()}",
)


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
    try:
        with _LOCK:
            c = _client()
            if not _STREAM_ENSURED:
                try:
                    c.create_log_stream(logGroupName=_LOG_GROUP, logStreamName=_LOG_STREAM)
                except c.exceptions.ResourceAlreadyExistsException:
                    pass
                _STREAM_ENSURED = True
            kwargs: dict[str, Any] = {
                "logGroupName": _LOG_GROUP,
                "logStreamName": _LOG_STREAM,
                "logEvents": [{"timestamp": ts_ms, "message": line}],
            }
            if _SEQUENCE_TOKEN is not None:
                kwargs["sequenceToken"] = _SEQUENCE_TOKEN
            try:
                resp = c.put_log_events(**kwargs)
            except c.exceptions.ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in ("InvalidSequenceTokenException", "DataAlreadyAcceptedException"):
                    raise
                streams = c.describe_log_streams(
                    logGroupName=_LOG_GROUP,
                    logStreamNamePrefix=_LOG_STREAM,
                    limit=50,
                )
                for s in streams.get("logStreams", []):
                    if s.get("logStreamName") == _LOG_STREAM:
                        _SEQUENCE_TOKEN = s.get("uploadSequenceToken")
                        break
                kwargs["sequenceToken"] = _SEQUENCE_TOKEN
                resp = c.put_log_events(**kwargs)
            _SEQUENCE_TOKEN = resp.get("nextSequenceToken")
    except Exception:
        logger.exception("Failed to emit message.lifecycle for message_id=%s", payload.get("message_id"))
