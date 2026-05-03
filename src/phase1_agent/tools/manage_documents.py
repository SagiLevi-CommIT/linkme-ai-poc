"""AgentCore tools: list and delete documents from the creator's KB."""

from __future__ import annotations

import logging
import os

import boto3

from common import config

logger = logging.getLogger(__name__)

_s3 = None


def _get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=config.AWS_REGION)
    return _s3


def list_documents(tenant_id: str) -> str:
    """List all documents in the creator's knowledge base.

    Args:
        tenant_id: The creator's tenant ID.

    Returns:
        Formatted list of documents with names and sizes.
    """
    try:
        resp = _get_s3().list_objects_v2(Bucket=config.KB_SOURCE_BUCKET, Prefix=f"{tenant_id}/")
    except Exception:
        logger.exception("Failed to list documents for %s", tenant_id)
        return f"Failed to list documents for tenant {tenant_id}."

    objects = resp.get("Contents", [])
    if not objects:
        return f"No documents found for tenant {tenant_id}. Upload some content to get started."

    lines = [f"Documents for {tenant_id} ({len(objects)} total):"]
    for obj in objects:
        name = obj["Key"].split("/", 1)[-1]
        size_kb = obj["Size"] / 1024
        lines.append(f"  - {name} ({size_kb:.1f} KB)")
    return "\n".join(lines)


def delete_document(tenant_id: str, doc_name: str) -> str:
    """Delete a document from the creator's knowledge base.

    Args:
        tenant_id: The creator's tenant ID.
        doc_name: Name of the document to delete.

    Returns:
        Confirmation message.
    """
    key = f"{tenant_id}/{doc_name}"
    try:
        _get_s3().delete_object(Bucket=config.KB_SOURCE_BUCKET, Key=key)
    except Exception:
        logger.exception("Failed to delete %s", key)
        return f"Failed to delete document '{doc_name}'."

    try:
        raw_resp = _get_s3().list_objects_v2(Bucket=config.RAW_UPLOADS_BUCKET, Prefix=f"{tenant_id}/")
        for obj in raw_resp.get("Contents", []):
            if doc_name.split(".")[0] in obj["Key"]:
                _get_s3().delete_object(Bucket=config.RAW_UPLOADS_BUCKET, Key=obj["Key"])
    except Exception:
        pass

    kb_id = config.BEDROCK_KB_ID
    if kb_id:
        try:
            bedrock_agent = boto3.client("bedrock-agent", region_name=config.AWS_REGION)
            ds_id = os.environ.get("KB_DS_ID", "EARAY9GAXN")
            bedrock_agent.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)
        except Exception:
            logger.warning("KB re-ingestion trigger failed after delete")

    logger.info("Deleted document %s for tenant %s", doc_name, tenant_id)
    return f"Document '{doc_name}' deleted. KB re-ingestion triggered."
