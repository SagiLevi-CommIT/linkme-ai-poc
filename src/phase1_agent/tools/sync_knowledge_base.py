"""AgentCore tool: trigger Bedrock KB ingestion sync."""

from __future__ import annotations

import logging

import boto3

from common import config

logger = logging.getLogger(__name__)

_bedrock_agent = None


def _get_client():  # type: ignore[no-untyped-def]
    global _bedrock_agent
    if _bedrock_agent is None:
        _bedrock_agent = boto3.client("bedrock-agent", region_name=config.AWS_REGION)
    return _bedrock_agent


def sync_knowledge_base(kb_id: str | None = None, data_source_id: str | None = None) -> str:
    """Trigger a Bedrock KB ingestion job.

    Args:
        kb_id: Knowledge base ID (defaults to BEDROCK_KB_ID env var).
        data_source_id: Data source ID to sync.

    Returns:
        Ingestion job status message.
    """
    kb_id = kb_id or config.BEDROCK_KB_ID
    if not kb_id:
        return "No KB ID configured. Set BEDROCK_KB_ID environment variable."

    if not data_source_id:
        return "data_source_id is required to trigger sync."

    try:
        response = _get_client().start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=data_source_id,
        )
        job_id = response.get("ingestionJob", {}).get("ingestionJobId", "unknown")
        logger.info("Started KB ingestion job %s for KB %s", job_id, kb_id)
        return f"KB ingestion started (job: {job_id}). Documents will be processed shortly."
    except Exception as e:
        logger.exception("Failed to start KB ingestion")
        return f"KB sync failed: {e}"
