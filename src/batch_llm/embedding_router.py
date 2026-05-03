"""Embedding-based model routing using prototype centroid vectors.

Compares the question embedding against pre-computed centroids for
simple / medium / complex question categories. Routes to Haiku or Sonnet
based on nearest centroid. Zero API cost -- reuses existing embedding.
"""

from __future__ import annotations

import json
import logging
import math
import os
from typing import Literal

from common import config

logger = logging.getLogger(__name__)

_centroids: dict[str, list[float]] = {}


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def load_centroids() -> None:
    """Load prototype centroids from DynamoDB, env var, or file.

    Checks sources in order:
    1. DynamoDB (profiles table, key '_system_routing_centroids')
    2. File path from ROUTING_CENTROIDS_PATH env var
    3. JSON string from ROUTING_CENTROIDS_JSON env var
    """
    global _centroids
    import boto3

    try:
        ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
        table_name = os.environ.get("PROFILES_TABLE", "ddb-linkme-poc-profiles")
        table = ddb.Table(table_name)
        resp = table.get_item(Key={"tenant_id": "_system_routing_centroids"})
        item = resp.get("Item")
        if item and item.get("profile"):
            data = item["profile"]
            if isinstance(data, str):
                _centroids = json.loads(data)
            else:
                _centroids = data
            logger.info("Loaded routing centroids from DynamoDB (%d categories)", len(_centroids))
            return
    except Exception:
        logger.warning("Could not load centroids from DynamoDB", exc_info=True)

    centroid_path = os.environ.get("ROUTING_CENTROIDS_PATH", "")
    if centroid_path and os.path.exists(centroid_path):
        with open(centroid_path) as f:
            _centroids = json.load(f)
        logger.info("Loaded routing centroids from %s", centroid_path)
        return

    raw = os.environ.get("ROUTING_CENTROIDS_JSON", "")
    if raw:
        _centroids = json.loads(raw)
        logger.info("Loaded routing centroids from env var")
        return

    logger.warning("No routing centroids configured; defaulting all to Haiku")


def route_question(embedding: list[float]) -> Literal["haiku", "sonnet"]:
    """Pick model based on embedding similarity to category centroids."""
    if not _centroids:
        return "haiku"

    scores = {
        category: _cosine_similarity(embedding, centroid)
        for category, centroid in _centroids.items()
    }

    best_category = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_category]

    if best_category == "complex" and best_score >= config.ROUTING_COMPLEX_THRESHOLD:
        return "sonnet"

    return "haiku"


def route_batch(embeddings: list[list[float]]) -> Literal["haiku", "sonnet"]:
    """Route a batch based on its most complex question."""
    for emb in embeddings:
        if route_question(emb) == "sonnet":
            return "sonnet"
    return "haiku"
