"""Correlation ID management for end-to-end tracing."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def new_correlation_id() -> str:
    cid = str(uuid.uuid4())
    _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    _correlation_id.set(cid)


def get_correlation_id() -> str:
    return _correlation_id.get()
