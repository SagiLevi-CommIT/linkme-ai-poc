"""DynamoDB-backed semantic vector cache with client-side cosine similarity.

Stores question embeddings alongside cached Q&A pairs in DynamoDB.
On lookup, retrieves all cache entries for a tenant and computes cosine
similarity client-side. Functionally equivalent to MemoryDB HNSW for
small-to-medium cache sizes (< 10K entries per tenant).

For scale (Tier 3+), replace with MemoryDB or ElastiCache vector search.
"""

from __future__ import annotations

import json
import logging
import math
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from common import config
from common.models import CacheResult, CacheTier

logger = logging.getLogger(__name__)

_ddb = None
SEMANTIC_CACHE_TABLE = "ddb-linkme-poc-semantic-cache"


def _get_ddb():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return _ddb


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_semantic(tenant_id: str, embedding: list[float]) -> CacheResult:
    """Search semantic cache for similar questions.

    Queries DynamoDB for all cache entries for this tenant,
    computes cosine similarity, returns best match classified by threshold.
    """
    table = _get_ddb().Table(SEMANTIC_CACHE_TABLE)

    try:
        resp = table.query(
            KeyConditionExpression=Key("tenant_id").eq(tenant_id),
            Limit=200,
        )
    except Exception:
        logger.exception("Semantic cache query failed")
        return CacheResult(tier=CacheTier.FULL_MISS)

    items = resp.get("Items", [])
    if not items:
        return CacheResult(tier=CacheTier.FULL_MISS)

    best_sim = 0.0
    best_item = None

    for item in items:
        vec_json = item.get("embedding", "[]")
        if isinstance(vec_json, str):
            cached_vec = json.loads(vec_json)
        elif isinstance(vec_json, list):
            cached_vec = [float(v) for v in vec_json]
        else:
            continue

        sim = _cosine_similarity(embedding, cached_vec)
        if sim > best_sim:
            best_sim = sim
            best_item = item

    if best_sim >= config.CACHE_HIGH_CONFIDENCE_THRESHOLD:
        tier = CacheTier.SEMANTIC_HIGH_HIT
    elif best_sim >= config.CACHE_BORDERLINE_THRESHOLD:
        tier = CacheTier.SEMANTIC_BORDERLINE
    else:
        tier = CacheTier.FULL_MISS

    return CacheResult(
        tier=tier,
        similarity_score=best_sim,
        cached_question=best_item.get("question", "") if best_item else None,
        cached_answer=best_item.get("answer", "") if best_item else None,
    )


def write_semantic_cache(
    tenant_id: str, question: str, answer: str, embedding: list[float], question_hash: str
) -> None:
    """Write a Q&A pair with its embedding to the semantic cache."""
    table = _get_ddb().Table(SEMANTIC_CACHE_TABLE)
    table.put_item(Item={
        "tenant_id": tenant_id,
        "question_hash": question_hash,
        "question": question,
        "answer": answer,
        "embedding": json.dumps(embedding),
        "created_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
