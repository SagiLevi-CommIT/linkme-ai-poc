"""Bedrock Titan V2 embedding client -- used when SageMaker endpoint is not available.

Sufficient for Tier 0-2 tests (up to 10K messages at 2K RPM).
For scale tests (Tier 3-4), switch to SageMaker endpoint.
"""

from __future__ import annotations

import json
import logging

import boto3

from common import config

logger = logging.getLogger(__name__)

_bedrock_client = None


def _get_client():  # type: ignore[no-untyped-def]
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client("bedrock-runtime", region_name=config.AWS_REGION)
    return _bedrock_client


def embed_text(text: str) -> list[float]:
    """Embed text using Bedrock Titan V2. Returns 1024-dimension vector."""
    body = json.dumps({"inputText": text})

    response = _get_client().invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        contentType="application/json",
        accept="application/json",
        body=body.encode("utf-8"),
    )

    result = json.loads(response["body"].read())
    return result["embedding"]


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts via sequential Titan V2 calls."""
    return [embed_text(t) for t in texts]
