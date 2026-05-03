"""AgentCore tool: preview a response using the creator's profile and KB.

This is an ESTIMATION for setup/testing purposes. It does NOT use the
production message pipeline (no queues, no cache, no batching, no delivery).
"""

from __future__ import annotations

import json
import logging

import boto3

from common import config
from common.schema import CreatorProfile
from phase1_agent.preview_utils import invoke_preview_llm, retrieve_kb_context, build_preview_prompt

logger = logging.getLogger(__name__)

_ddb = None


def _get_ddb():  # type: ignore[no-untyped-def]
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return _ddb


def preview_answer(tenant_id: str, question: str) -> str:
    """Generate a preview response using the creator's profile and KB.

    This is an estimated preview, not a real pipeline response.

    Args:
        tenant_id: The creator's tenant ID.
        question: A sample fan question to test.

    Returns:
        The AI-generated preview response.
    """
    table = _get_ddb().Table(config.PROFILES_TABLE)
    resp = table.get_item(Key={"tenant_id": tenant_id})
    item = resp.get("Item")
    if not item:
        return f"No profile found for tenant '{tenant_id}'. Create a profile first."

    profile_data = item.get("profile", {})
    if isinstance(profile_data, str):
        profile_data = json.loads(profile_data)

    try:
        profile = CreatorProfile(**profile_data)
    except Exception as e:
        return f"Invalid profile data: {e}"

    kb_context = retrieve_kb_context(question, tenant_id, top_k=3)
    system_prompt = build_preview_prompt(profile, kb_context=kb_context)
    prompt = f"{system_prompt}\n\nUSER MESSAGE:\n{question}"

    answer = invoke_preview_llm(prompt)
    return f"Preview response:\n\n{answer}"
