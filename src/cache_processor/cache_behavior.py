"""Three-tier cache hit/miss/borderline classification logic."""

from __future__ import annotations

import logging

from common.models import CacheResult, CacheTier

logger = logging.getLogger(__name__)


def classify_cache_result(result: CacheResult) -> CacheTier:
    """Determine the action tier based on cache lookup results.

    Returns the CacheTier which dictates the next step:
    - EXACT_HIT / SEMANTIC_HIGH_HIT: return cached answer directly
    - SEMANTIC_BORDERLINE: send to batch queue for lightweight adaptation
    - FULL_MISS: send to batch queue for full RAG + LLM
    """
    return result.tier


def should_return_immediately(tier: CacheTier) -> bool:
    return tier in (CacheTier.EXACT_HIT, CacheTier.SEMANTIC_HIGH_HIT)


def should_send_to_batch_queue(tier: CacheTier) -> bool:
    return tier in (CacheTier.SEMANTIC_BORDERLINE, CacheTier.FULL_MISS)
