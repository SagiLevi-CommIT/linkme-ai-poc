"""AgentCore tool: validate and store a CreatorProfile in DynamoDB."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import boto3

from common import config
from common.schema import CreatorProfile

logger = logging.getLogger(__name__)

_ddb = None


def _get_ddb():  # type: ignore[no-untyped-def]
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return _ddb


def create_profile(profile_json: str) -> str:
    """Validate and store a creator profile.

    Args:
        profile_json: JSON string of the creator profile data.

    Returns:
        Confirmation message with the creator_id.
    """
    try:
        data = json.loads(profile_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

    now = datetime.now(timezone.utc).isoformat()
    data.setdefault("created_at", now)
    data.setdefault("updated_at", now)

    try:
        profile = CreatorProfile(**data)
    except Exception as e:
        return f"Profile validation failed: {e}"

    table = _get_ddb().Table(config.PROFILES_TABLE)
    table.put_item(
        Item={
            "tenant_id": profile.creator.creator_id,
            "profile": profile.model_dump_json(),
        }
    )

    logger.info("Created profile for %s", profile.creator.creator_id)
    return f"Profile created for {profile.creator.creator_name} (ID: {profile.creator.creator_id})"
