"""Self-contained preview utilities for Component 1 (AgentCore / Creator Setup).

Provides Bedrock LLM invocation, KB retrieval, and prompt construction
for preview/estimation purposes ONLY. This module has ZERO dependencies
on the production message pipeline (batch_llm, cache_processor, delivery).

Acceptable imports: common.config (shared env), common.schema (shared models), boto3.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

import boto3

from common import config
from common.schema import CreatorProfile, ToneConfig

logger = logging.getLogger(__name__)

_TONE_PRESETS = {
    "friendly": "Be warm, approachable, and use a conversational tone.",
    "professional": "Maintain a polished, business-appropriate tone.",
    "playful": "Be fun, witty, and lighthearted.",
    "casual": "Keep it relaxed and informal, like texting a friend.",
    "formal": "Use proper grammar and a respectful, measured tone.",
}

_bedrock_runtime = None
_kb_runtime = None


def _get_bedrock_runtime():
    global _bedrock_runtime
    if _bedrock_runtime is None:
        _bedrock_runtime = boto3.client("bedrock-runtime", region_name=config.AWS_REGION)
    return _bedrock_runtime


def _get_kb_runtime():
    global _kb_runtime
    if _kb_runtime is None:
        _kb_runtime = boto3.client("bedrock-agent-runtime", region_name=config.AWS_REGION)
    return _kb_runtime


def invoke_preview_llm(prompt: str, max_tokens: int = 300) -> str:
    """Invoke Bedrock Haiku for a preview response. Returns generated text."""
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })

    response = _get_bedrock_runtime().invoke_model(
        modelId=config.BEDROCK_HAIKU_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body.encode("utf-8"),
    )

    result = json.loads(response["body"].read())
    content_blocks = result.get("content", [])
    return "".join(b["text"] for b in content_blocks if b.get("type") == "text")


def retrieve_kb_context(query: str, tenant_id: str, top_k: int = 3) -> str:
    """Retrieve relevant KB chunks for a tenant. Returns empty string if KB unavailable."""
    if not config.BEDROCK_KB_ID:
        logger.info("BEDROCK_KB_ID not set; preview will use profile context only")
        return ""

    try:
        response = _get_kb_runtime().retrieve(
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
        logger.exception("Preview KB retrieval failed for tenant %s", tenant_id)
        return ""


def build_preview_prompt(profile: CreatorProfile, kb_context: str = "") -> str:
    """Build a preview system prompt from the creator's profile and optional KB context."""
    tone = profile.agent.tone
    if tone.preset != "custom":
        tone_block = _TONE_PRESETS.get(tone.preset, "")
    elif tone.parameters:
        p = tone.parameters
        tone_block = (
            f"Formality: {p.formality}/100. "
            f"Message length: {p.message_length}/100. "
            f"Emoji usage: {p.emoji_usage}/100. "
            f"Energy level: {p.energy_level}/100."
        )
    else:
        tone_block = ""

    rules = "\n".join(
        f"{i+1}. {rule}" for i, rule in enumerate(profile.agent.response_rules)
    )

    return (
        f"You are an AI assistant for {profile.creator.creator_name}.\n"
        f"Your goal: {profile.agent.main_goal}\n\n"
        f"TONE INSTRUCTIONS:\n{tone_block}\n\n"
        f"HARD RULES (you MUST follow these):\n{rules}\n\n"
        f'If the user asks about anything outside your goal, respond exactly with:\n'
        f'"{profile.agent.out_of_scope_reply}"\n\n'
        f"CONTEXT FROM KNOWLEDGE BASE:\n{kb_context}"
    )
