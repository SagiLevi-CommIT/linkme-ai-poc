"""Runtime configuration from environment variables.

Reads the environment and exposes typed constants. All values have sane
defaults so that unit tests and local smoke runs work without an
`.env` file. Each EKS deployment (messages-pusher, cache-service,
llm-service) sets the relevant subset via a Kubernetes ConfigMap.
"""

from __future__ import annotations

import os
import json
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _project_config() -> dict[str, str]:
    path = Path(__file__).resolve().parents[2] / "config" / "bedrock_kb_creators.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {str(key): str(value) for key, value in data.items() if value is not None}


_KB_SETUP = _project_config()


AWS_REGION = _env("AWS_REGION_OVERRIDE", _env("AWS_REGION", "us-west-2"))
AWS_PROFILE = _env("AWS_PROFILE", "")

# ----------------------------------------------------------------
# SQS — new simulator queues (replaces legacy INGESTION/BATCH/RESPONSE)
# ----------------------------------------------------------------
INCOMING_QUEUE_URL = _env("INCOMING_QUEUE_URL")
AI_PROCESSING_QUEUE_URL = _env("AI_PROCESSING_QUEUE_URL")

# ----------------------------------------------------------------
# DynamoDB
# ----------------------------------------------------------------
PROFILES_TABLE = _env("PROFILES_TABLE", "ddb-linkme-poc-profiles")
CACHE_TABLE = _env("CACHE_TABLE", "ddb-linkme-poc-cache")
RESULTS_TABLE = _env("RESULTS_TABLE", "ddb-linkme-ai-poc-results")

# Legacy — only the api Lambda still writes here (per-message status rows).
# EKS services write to RESULTS_TABLE instead.
MESSAGES_TABLE = _env("MESSAGES_TABLE", "ddb-linkme-poc-messages")

# ----------------------------------------------------------------
# SageMaker
# ----------------------------------------------------------------
SAGEMAKER_ENDPOINT_NAME = _env("SAGEMAKER_ENDPOINT_NAME", "linkme-poc-embedding")

# ----------------------------------------------------------------
# S3
# ----------------------------------------------------------------
RAW_UPLOADS_BUCKET = _env("RAW_UPLOADS_BUCKET", "linkme-poc-raw-uploads")
KB_SOURCE_BUCKET = _env(
    "KB_SOURCE_BUCKET", _KB_SETUP.get("KB_SOURCE_BUCKET", "linkme-poc-kb-source")
)
KB_SOURCE_PREFIX = _env("KB_SOURCE_PREFIX", _KB_SETUP.get("KB_SOURCE_PREFIX", ""))
INPUT_MESSAGES_BUCKET = _env("INPUT_MESSAGES_BUCKET", "")

# ----------------------------------------------------------------
# Nova (multimodal content extraction) — used by the preprocessing Lambda
# ----------------------------------------------------------------
NOVA_MODEL_ID = _env("NOVA_MODEL_ID", "us.amazon.nova-lite-v1:0")

# ----------------------------------------------------------------
# MemoryDB (semantic cache + rate limit)
# ----------------------------------------------------------------
MEMORYDB_ENDPOINT = _env("MEMORYDB_ENDPOINT")
MEMORYDB_PORT = int(_env("MEMORYDB_PORT", "6379"))

# ----------------------------------------------------------------
# Bedrock
# ----------------------------------------------------------------
BEDROCK_HAIKU_MODEL_ID = _env(
    "BEDROCK_HAIKU_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)
BEDROCK_SONNET_MODEL_ID = _env(
    "BEDROCK_SONNET_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)
BEDROCK_KB_ID = _env(
    "BEDROCK_KB_ID",
    _env("KB_ID", _KB_SETUP.get("BEDROCK_KB_ID", "")),
)
BEDROCK_KB_DS_ID = _env(
    "BEDROCK_KB_DS_ID",
    _env("KB_DS_ID", _KB_SETUP.get("BEDROCK_KB_DS_ID", "")),
)

# ----------------------------------------------------------------
# Cache thresholds
# ----------------------------------------------------------------
CACHE_EXACT_MATCH_ENABLED = _env("CACHE_EXACT_MATCH_ENABLED", "true") == "true"
CACHE_HIGH_CONFIDENCE_THRESHOLD = float(
    _env("CACHE_HIGH_CONFIDENCE_THRESHOLD", "0.92")
)
CACHE_BORDERLINE_THRESHOLD = float(_env("CACHE_BORDERLINE_THRESHOLD", "0.82"))

# ----------------------------------------------------------------
# Batch settings (applies to LLM Service)
# ----------------------------------------------------------------
BATCH_WINDOW_SECONDS = int(_env("BATCH_WINDOW_SECONDS", "2"))
BATCH_MAX_SIZE = int(_env("BATCH_MAX_SIZE", "10"))

# ----------------------------------------------------------------
# Routing (LLM Service — model selection based on centroid similarity)
# ----------------------------------------------------------------
ROUTING_SIMPLE_THRESHOLD = float(_env("ROUTING_SIMPLE_THRESHOLD", "0.65"))
ROUTING_COMPLEX_THRESHOLD = float(_env("ROUTING_COMPLEX_THRESHOLD", "0.65"))

# ----------------------------------------------------------------
# LLM token limits
# ----------------------------------------------------------------
LLM_MAX_TOKENS_HAIKU = int(_env("LLM_MAX_TOKENS_HAIKU", "300"))
LLM_MAX_TOKENS_SONNET = int(_env("LLM_MAX_TOKENS_SONNET", "600"))
