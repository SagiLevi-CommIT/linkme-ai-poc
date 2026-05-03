"""AgentCore tool: update specific fields of an existing CreatorProfile."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import boto3

from common import config
from common.schema import CreatorProfile

logger = logging.getLogger(__name__)

_ddb = None


def _get_ddb():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return _ddb


def update_profile(tenant_id: str, updates_json: str) -> str:
    """Update specific fields of an existing creator profile.

    Args:
        tenant_id: The creator's tenant ID.
        updates_json: JSON string with fields to update.

    Returns:
        Confirmation message with updated fields.
    """
    try:
        updates = json.loads(updates_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

    table = _get_ddb().Table(config.PROFILES_TABLE)
    resp = table.get_item(Key={"tenant_id": tenant_id})
    item = resp.get("Item")
    if not item:
        return f"No profile found for tenant '{tenant_id}'. Create a profile first."

    profile_data = item.get("profile", "{}")
    if isinstance(profile_data, str):
        profile_data = json.loads(profile_data)

    _deep_merge(profile_data, updates)
    profile_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    try:
        profile = CreatorProfile(**profile_data)
    except Exception as e:
        return f"Update would create invalid profile: {e}"

    table.put_item(Item={"tenant_id": tenant_id, "profile": profile.model_dump_json()})
    logger.info("Updated profile for %s", tenant_id)
    return f"Profile updated for {tenant_id}. Changed fields: {list(updates.keys())}"


def _deep_merge(base: dict, updates: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
