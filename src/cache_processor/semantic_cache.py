"""MemoryDB-backed semantic cache: hash check + HNSW vector search."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import struct

import boto3

from common import config
from common.models import CacheResult, CacheTier

logger = logging.getLogger(__name__)

_ddb = None
_redis = None
_index_ready = False

INDEX_NAME = "idx:semantic_cache"
KEY_PREFIX = "cache:"
VECTOR_DIM = 768


def _pack_vector(embedding: list[float]) -> bytes:
    """Pack a Python list of floats as MemoryDB FLOAT32 vector bytes."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def ensure_index() -> None:
    """Create the FT index if it doesn't exist. Idempotent.

    MemoryDB FT.CREATE fails if the index already exists — we swallow that
    specific error. Any other failure propagates because it indicates a
    configuration problem (e.g. search-enabled=no on the cluster).
    """
    global _index_ready
    if _index_ready:
        return
    r = _get_redis()
    if r is None:
        return
    try:
        r.execute_command(
            "FT.CREATE", INDEX_NAME,
            "ON", "HASH",
            "PREFIX", "1", KEY_PREFIX,
            "SCHEMA",
            "tenant_id", "TAG",
            "question", "TEXT",
            "answer", "TEXT",
            "vector", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32",
            "DIM", str(VECTOR_DIM),
            "DISTANCE_METRIC", "COSINE",
        )
        logger.info("Created MemoryDB vector index %s", INDEX_NAME)
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg or "index already" in msg:
            logger.info("MemoryDB vector index %s already exists", INDEX_NAME)
        else:
            logger.exception("Failed to create MemoryDB vector index")
            raise
    _index_ready = True


def _get_ddb():  # type: ignore[no-untyped-def]
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return _ddb


def _get_redis():  # type: ignore[no-untyped-def]
    global _redis
    if _redis is None:
        if not config.MEMORYDB_ENDPOINT:
            return None
        import redis as redis_lib

        # decode_responses=False — we need raw bytes for the vector field
        # on FT.SEARCH results and also for the vector blob we write.
        _redis = redis_lib.Redis(
            host=config.MEMORYDB_ENDPOINT,
            port=config.MEMORYDB_PORT,
            decode_responses=False,
            ssl=True,
        )
    return _redis


def normalize_question(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def question_hash(normalized_text: str) -> str:
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def check_exact_match(tenant_id: str, q_hash: str) -> CacheResult | None:
    """Tier 1: DynamoDB exact hash lookup."""
    if not config.CACHE_EXACT_MATCH_ENABLED:
        return None
    table = _get_ddb().Table(config.CACHE_TABLE)
    resp = table.get_item(Key={"pk": f"{tenant_id}#{q_hash}"})
    item = resp.get("Item")
    if item:
        return CacheResult(
            tier=CacheTier.EXACT_HIT,
            similarity_score=1.0,
            cached_question=item.get("question", ""),
            cached_answer=item.get("answer", ""),
        )
    return None


def search_vector(tenant_id: str, embedding: list[float]) -> CacheResult:
    """Tier 2/3: MemoryDB HNSW vector search filtered by tenant_id.

    Returns the best match with its similarity score and the cache tier classification.
    When MemoryDB is not configured, returns FULL_MISS for all queries.
    """
    r = _get_redis()
    if r is None:
        logger.info("MemoryDB not configured; treating as full miss")
        return CacheResult(tier=CacheTier.FULL_MISS)

    # Ensure the index exists (idempotent; runs once per process).
    try:
        ensure_index()
    except Exception:
        return CacheResult(tier=CacheTier.FULL_MISS)

    query_vec = _pack_vector(embedding)

    try:
        # MemoryDB's RediSearch does not support hybrid pre-filter + KNN in one
        # query. Use pure KNN on the full index and post-filter by tenant_id
        # in Python. K=5 gives us the top matches; we keep the first one whose
        # tenant_id matches this request.
        results = r.execute_command(
            "FT.SEARCH",
            INDEX_NAME,
            "*=>[KNN 5 @vector $vec AS score]",
            "PARAMS", "2", "vec", query_vec,
            "SORTBY", "score",
            "LIMIT", "0", "5",
            "RETURN", "4", "score", "question", "answer", "tenant_id",
            "DIALECT", "2",
        )
    except Exception:
        logger.exception("MemoryDB vector search failed, treating as full miss")
        return CacheResult(tier=CacheTier.FULL_MISS)

    if not results or results[0] == 0:
        return CacheResult(tier=CacheTier.FULL_MISS)

    # results layout: [count, doc_id_1, [k1, v1, k2, v2, ...], doc_id_2, [...], ...]
    # Walk the top-K and take the first match with matching tenant_id.
    matched: dict[str, str] | None = None
    for i in range(2, len(results), 2):
        fields = results[i]
        field_map: dict[str, str] = {}
        for j in range(0, len(fields), 2):
            k = fields[j].decode() if isinstance(fields[j], (bytes, bytearray)) else fields[j]
            v = fields[j + 1]
            if isinstance(v, (bytes, bytearray)) and k != "vector":
                v = v.decode(errors="replace")
            field_map[k] = v
        if field_map.get("tenant_id") == tenant_id:
            matched = field_map
            break

    if matched is None:
        return CacheResult(tier=CacheTier.FULL_MISS)
    field_map = matched

    similarity = 1.0 - float(field_map.get("score", "1.0"))

    if similarity >= config.CACHE_HIGH_CONFIDENCE_THRESHOLD:
        tier = CacheTier.SEMANTIC_HIGH_HIT
    elif similarity >= config.CACHE_BORDERLINE_THRESHOLD:
        tier = CacheTier.SEMANTIC_BORDERLINE
    else:
        tier = CacheTier.FULL_MISS

    return CacheResult(
        tier=tier,
        similarity_score=similarity,
        cached_question=field_map.get("question"),
        cached_answer=field_map.get("answer"),
    )


def write_to_cache(
    tenant_id: str,
    question: str,
    answer: str,
    embedding: list[float],
    *,
    run_id: str = "",
    seed_source: str = "",
) -> None:
    """Write a new Q&A pair to both DynamoDB (exact) and MemoryDB (semantic)."""
    normalized = normalize_question(question)
    q_hash = question_hash(normalized)

    table = _get_ddb().Table(config.CACHE_TABLE)
    item = {
        "pk": f"{tenant_id}#{q_hash}",
        "tenant_id": tenant_id,
        "question": question,
        "answer": answer,
    }
    if run_id:
        item["run_id"] = run_id
    if seed_source:
        item["seed_source"] = seed_source
    table.put_item(Item=item)

    r = _get_redis()
    if r is None:
        return
    try:
        ensure_index()
    except Exception:
        return
    key = f"{KEY_PREFIX}{tenant_id}:{q_hash}"
    mapping = {
        "tenant_id": tenant_id,
        "question": question,
        "answer": answer,
        # FLOAT32 raw bytes (not JSON). KNN indexing requires this format.
        "vector": _pack_vector(embedding),
    }
    if run_id:
        mapping["run_id"] = run_id
    if seed_source:
        mapping["seed_source"] = seed_source
    r.hset(key, mapping=mapping)
