"""Bedrock LLM invocation client with CRIS and model selection."""

from __future__ import annotations

import json
import logging
from typing import Literal

import boto3

from common import config

logger = logging.getLogger(__name__)

_bedrock_client = None


def _get_client():  # type: ignore[no-untyped-def]
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client("bedrock-runtime", region_name=config.AWS_REGION)
    return _bedrock_client


def invoke_llm(
    prompt: str,
    model: Literal["haiku", "sonnet"] = "haiku",
    max_tokens: int | None = None,
) -> str:
    """Invoke Bedrock LLM and return the text response."""
    model_id = (
        config.BEDROCK_HAIKU_MODEL_ID
        if model == "haiku"
        else config.BEDROCK_SONNET_MODEL_ID
    )
    if max_tokens is None:
        max_tokens = (
            config.LLM_MAX_TOKENS_HAIKU
            if model == "haiku"
            else config.LLM_MAX_TOKENS_SONNET
        )

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    )

    response = _get_client().invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=body.encode("utf-8"),
    )

    result = json.loads(response["body"].read())
    content_blocks = result.get("content", [])
    text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
    return "".join(text_parts)
