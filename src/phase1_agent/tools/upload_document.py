"""AgentCore tool: upload a file to S3 under the tenant's KB prefix."""

from __future__ import annotations

import logging
import os

import boto3

from common import config

logger = logging.getLogger(__name__)

_s3 = None


def _get_s3():  # type: ignore[no-untyped-def]
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=config.AWS_REGION)
    return _s3


KB_BUCKET = f"linkme-poc-kb-source"


def upload_document(tenant_id: str, file_path: str, doc_name: str) -> str:
    """Upload a document to the tenant's KB folder in S3.

    Args:
        tenant_id: The creator's tenant ID.
        file_path: Local path to the file to upload.
        doc_name: Display name for the document.

    Returns:
        Confirmation with the S3 key.
    """
    if not os.path.exists(file_path):
        return f"File not found: {file_path}"

    ext = os.path.splitext(file_path)[1]
    s3_key = f"{tenant_id}/{doc_name}{ext}"

    _get_s3().upload_file(file_path, KB_BUCKET, s3_key)

    logger.info("Uploaded %s to s3://%s/%s", doc_name, KB_BUCKET, s3_key)
    return f"Uploaded '{doc_name}' to KB storage (key: {s3_key})"
