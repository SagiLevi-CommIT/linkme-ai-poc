"""SageMaker invoke_endpoint wrapper for question embedding.

Backed by a TEI (Text Embeddings Inference) endpoint serving
bge-base-en-v1.5. TEI returns sentence-level embeddings directly
(server-side pooling), so this client just serializes, invokes, and
returns the vectors. TEI also performs server-side dynamic batching
across concurrent requests, so even single-text calls are efficient
under load.
"""

from __future__ import annotations

import json
import logging

import boto3

from common import config

logger = logging.getLogger(__name__)

_sm_client = None


def _get_client():  # type: ignore[no-untyped-def]
    global _sm_client
    if _sm_client is None:
        _sm_client = boto3.client("sagemaker-runtime", region_name=config.AWS_REGION)
    return _sm_client


def _invoke(body: dict) -> list:
    payload = json.dumps(body)
    response = _get_client().invoke_endpoint(
        EndpointName=config.SAGEMAKER_ENDPOINT_NAME,
        ContentType="application/json",
        Body=payload.encode("utf-8"),
    )
    return json.loads(response["Body"].read().decode("utf-8"))


def embed_text(text: str) -> list[float]:
    """Embed a single text string. Returns a 768-dim sentence vector."""
    result = _invoke({"inputs": text})
    if isinstance(result, list) and result and isinstance(result[0], list):
        return result[0]
    if isinstance(result, list) and result and isinstance(result[0], (int, float)):
        return result  # type: ignore[return-value]
    raise ValueError(f"Unexpected TEI response shape: {type(result)}")


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts in a single SageMaker call.

    TEI returns a 2D list: [n_inputs][embedding_dim]. No mean-pooling
    needed — TEI pools server-side.
    """
    if not texts:
        return []
    result = _invoke({"inputs": texts})
    if not isinstance(result, list) or not result or not isinstance(result[0], list):
        raise ValueError(f"Unexpected TEI batch response shape: {type(result)}")
    return result
