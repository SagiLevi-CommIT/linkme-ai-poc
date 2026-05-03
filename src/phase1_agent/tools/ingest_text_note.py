"""AgentCore tool: directly add a text note to the creator's KB."""

from __future__ import annotations

import logging
import os
import uuid

import boto3

from common import config

logger = logging.getLogger(__name__)

_s3 = None
_bedrock_agent = None


def _get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=config.AWS_REGION)
    return _s3


def _get_bedrock_agent():
    global _bedrock_agent
    if _bedrock_agent is None:
        _bedrock_agent = boto3.client("bedrock-agent", region_name=config.AWS_REGION)
    return _bedrock_agent


def ingest_text_note(tenant_id: str, content: str, doc_name: str = "") -> str:
    """Add a text note directly to the creator's knowledge base.

    Use this when the creator describes information in conversation.

    Args:
        tenant_id: The creator's tenant ID.
        content: The text content to add to the KB.
        doc_name: Display name for the note (auto-generated if empty).

    Returns:
        Confirmation message.
    """
    if not content or len(content.strip()) < 10:
        return "Please provide at least 10 characters of content."

    if not doc_name:
        doc_name = f"note_{uuid.uuid4().hex[:8]}"

    key = f"{tenant_id}/{doc_name}.txt"
    _get_s3().put_object(
        Bucket=config.KB_SOURCE_BUCKET, Key=key,
        Body=content.encode("utf-8"), ContentType="text/plain",
        Metadata={"tenant_id": tenant_id, "source_type": "text"},
    )

    kb_id = config.BEDROCK_KB_ID
    if kb_id:
        try:
            ds_id = os.environ.get("KB_DS_ID", "EARAY9GAXN")
            _get_bedrock_agent().start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)
        except Exception:
            logger.warning("KB re-ingestion trigger failed")

    logger.info("Added text note '%s' for tenant %s (%d chars)", doc_name, tenant_id, len(content))
    return f"Text note '{doc_name}' added to your knowledge base ({len(content)} characters). KB re-ingestion triggered."
