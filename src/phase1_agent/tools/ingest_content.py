"""AgentCore tool: upload raw content to S3 and trigger preprocessing."""

from __future__ import annotations

import json
import logging
import os
import uuid

import boto3

from common import config

logger = logging.getLogger(__name__)

_s3 = None
_lambda_client = None


def _get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=config.AWS_REGION)
    return _s3


def _get_lambda():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda", region_name=config.AWS_REGION)
    return _lambda_client


def ingest_content(tenant_id: str, file_path: str, doc_name: str = "") -> str:
    """Upload a file and trigger preprocessing to extract text for the KB.

    Supports PDF, images (png/jpg/gif/webp), DOCX, and plain text files.

    Args:
        tenant_id: The creator's tenant ID.
        file_path: Local path to the file to upload.
        doc_name: Display name for the document (defaults to filename).

    Returns:
        Status message about the ingestion.
    """
    if not os.path.exists(file_path):
        return f"File not found: {file_path}"

    if not doc_name:
        doc_name = os.path.basename(file_path)

    ext = os.path.splitext(file_path)[1].lower()
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    raw_key = f"{tenant_id}/{doc_id}/{doc_name}"

    _get_s3().upload_file(file_path, config.RAW_UPLOADS_BUCKET, raw_key)
    logger.info("Uploaded raw file to s3://%s/%s", config.RAW_UPLOADS_BUCKET, raw_key)

    try:
        _get_lambda().invoke(
            FunctionName="linkme-poc-preprocessing",
            InvocationType="Event",
            Payload=json.dumps({
                "tenant_id": tenant_id,
                "source_type": _detect_type(ext),
                "bucket": config.RAW_UPLOADS_BUCKET,
                "key": raw_key,
                "doc_name": os.path.splitext(doc_name)[0],
            }).encode(),
        )
    except Exception:
        logger.exception("Failed to invoke preprocessing Lambda")
        return f"File uploaded but preprocessing trigger failed. File: {raw_key}"

    return (
        f"File '{doc_name}' uploaded and preprocessing started. "
        f"The content will be extracted and added to your knowledge base automatically. "
        f"This usually takes 10-30 seconds."
    )


def _detect_type(ext: str) -> str:
    mapping = {
        ".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image",
        ".gif": "image", ".webp": "image", ".docx": "docx",
    }
    return mapping.get(ext, "text")
