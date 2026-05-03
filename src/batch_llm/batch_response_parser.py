"""Parse and validate structured JSON responses from batch LLM calls."""

from __future__ import annotations

import json
import logging
import re

from common.models import BatchResponse

logger = logging.getLogger(__name__)


def parse_batch_response(raw_text: str, expected_ids: list[str]) -> BatchResponse | None:
    """Attempt to parse a batch LLM response into a validated BatchResponse.

    Tries in order:
    1. Direct JSON parse
    2. Strip markdown code fences, re-parse
    3. Regex extraction of JSON object
    """
    text = raw_text.strip()

    parsed = _try_parse(text)
    if parsed:
        return _validate(parsed, expected_ids)

    stripped = _strip_code_fences(text)
    if stripped != text:
        parsed = _try_parse(stripped)
        if parsed:
            return _validate(parsed, expected_ids)

    extracted = _regex_extract(text)
    if extracted:
        parsed = _try_parse(extracted)
        if parsed:
            return _validate(parsed, expected_ids)

    logger.warning("All parse attempts failed for batch response")
    return None


def _try_parse(text: str) -> BatchResponse | None:
    try:
        data = json.loads(text)
        return BatchResponse(**data)
    except (json.JSONDecodeError, Exception):
        return None


def _strip_code_fences(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def _regex_extract(text: str) -> str | None:
    match = re.search(r'\{[^{}]*"answers"\s*:\s*\[.*?\]\s*\}', text, re.DOTALL)
    return match.group(0) if match else None


def _validate(response: BatchResponse, expected_ids: list[str]) -> BatchResponse | None:
    returned_ids = {a.id for a in response.answers}
    missing = set(expected_ids) - returned_ids
    if missing:
        logger.warning("Batch response missing IDs: %s", missing)
        return None
    return response
