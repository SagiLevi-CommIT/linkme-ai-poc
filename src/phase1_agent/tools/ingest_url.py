"""AgentCore tool: fetch a URL and ingest its content into the KB."""

from __future__ import annotations

import json
import logging
import uuid
from urllib.parse import urlparse

import boto3

from common import config

logger = logging.getLogger(__name__)

_lambda_client = None


def _get_lambda():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda", region_name=config.AWS_REGION)
    return _lambda_client


def ingest_url(tenant_id: str, url: str, doc_name: str = "") -> str:
    """Fetch a URL, extract its content, and add it to the creator's KB.

    Args:
        tenant_id: The creator's tenant ID.
        url: The URL to fetch and ingest.
        doc_name: Display name for the document (defaults to URL domain).

    Returns:
        Status message about the ingestion.
    """
    if not url or not url.startswith(("http://", "https://")):
        return "Please provide a valid URL starting with http:// or https://"

    if not doc_name:
        parsed = urlparse(url)
        doc_name = f"url_{parsed.netloc.replace('.', '_')}_{uuid.uuid4().hex[:6]}"

    try:
        _get_lambda().invoke(
            FunctionName="linkme-poc-preprocessing",
            InvocationType="Event",
            Payload=json.dumps({
                "tenant_id": tenant_id,
                "source_type": "url",
                "url": url,
                "doc_name": doc_name,
            }).encode(),
        )
    except Exception:
        logger.exception("Failed to invoke preprocessing Lambda for URL: %s", url)
        return f"Failed to start URL ingestion for {url}. Please try again."

    return (
        f"URL '{url}' submitted for ingestion. The system will fetch the page, "
        f"extract the main content, and add it to your knowledge base. "
        f"This usually takes 10-30 seconds."
    )
