"""Build ``message.lifecycle`` payloads per PoC supplier spec."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common.models import CacheTier

LIFECYCLE_EVENT = "message.lifecycle"

# Supplier path enum values
PATH_CACHE_HIT_EXACT = "cache_hit_exact"
PATH_CACHE_HIT_SEMANTIC = "cache_hit_semantic"
PATH_CACHE_MISS = "cache_miss"


def normalize_received_at_iso(ts: str) -> str:
    """Normalize ingestion timestamp to UTC with Z suffix for JSON logs."""
    if not ts:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    s = ts.strip()
    if s.endswith("Z"):
        return s
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except ValueError:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def path_for_cache_tier(tier: CacheTier) -> str:
    if tier == CacheTier.EXACT_HIT:
        return PATH_CACHE_HIT_EXACT
    if tier in (CacheTier.SEMANTIC_HIGH_HIT, CacheTier.SEMANTIC_BORDERLINE):
        return PATH_CACHE_HIT_SEMANTIC
    return PATH_CACHE_MISS


def total_latency_ms(received_at_iso: str, responded_at_iso: str) -> int:
    try:
        ra = datetime.fromisoformat(received_at_iso.replace("Z", "+00:00"))
        rb = datetime.fromisoformat(responded_at_iso.replace("Z", "+00:00"))
        if ra.tzinfo is None:
            ra = ra.replace(tzinfo=timezone.utc)
        if rb.tzinfo is None:
            rb = rb.replace(tzinfo=timezone.utc)
        delta = rb - ra
        ms = int(delta.total_seconds() * 1000)
        if ms < 0:
            return 1
        return ms
    except Exception:
        return 0


def build_lifecycle_payload(
    *,
    message_id: str,
    creator_id: str,
    received_at: str,
    responded_at: str,
    path: str,
    status: str,
    error_stage: str | None = None,
) -> dict[str, Any]:
    recv = normalize_received_at_iso(received_at)
    resp = normalize_received_at_iso(responded_at)
    lat = total_latency_ms(recv, resp)
    if lat == 0 and status == "success":
        lat = 1
    payload: dict[str, Any] = {
        "event": LIFECYCLE_EVENT,
        "message_id": message_id,
        "creator_id": creator_id,
        "received_at": recv,
        "responded_at": resp,
        "total_latency_ms": lat,
        "path": path,
        "status": status,
        "error_stage": error_stage,
    }
    return payload
