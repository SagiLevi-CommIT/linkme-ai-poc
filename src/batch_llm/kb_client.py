"""Bedrock Knowledge Base retrieval client (once per batch)."""

from __future__ import annotations

import logging

import boto3

from common import config

logger = logging.getLogger(__name__)

_kb_client = None


def _get_client():  # type: ignore[no-untyped-def]
    global _kb_client
    if _kb_client is None:
        _kb_client = boto3.client("bedrock-agent-runtime", region_name=config.AWS_REGION)
    return _kb_client


def retrieve_context(query: str, tenant_id: str, top_k: int = 5) -> str:
    """Retrieve relevant KB chunks for a tenant, return as concatenated text."""
    if not config.BEDROCK_KB_ID:
        logger.warning("BEDROCK_KB_ID not configured; skipping KB retrieval")
        return ""

    try:
        response = _get_client().retrieve(
            knowledgeBaseId=config.BEDROCK_KB_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": top_k,
                    "filter": {
                        "equals": {"key": "tenant_id", "value": tenant_id}
                    },
                }
            },
        )

        chunks = []
        for result in response.get("retrievalResults", []):
            text = result.get("content", {}).get("text", "")
            if text:
                chunks.append(text)

        return "\n---\n".join(chunks)

    except Exception:
        logger.exception("KB retrieval failed for tenant %s", tenant_id)
        return ""
