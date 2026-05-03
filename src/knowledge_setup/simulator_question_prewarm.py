"""Generate and prewarm simulator questions per creator.

This side process intentionally does not touch the KB source prefix. It uses the
prepared creator profile/source text as prompt context, writes exact cache rows
to DynamoDB, writes semantic seed rows directly to MemoryDB using the same key
shape as cache-service, and uploads simulator-compatible JSONL under
``messages/{run_id}/batch-*.jsonl``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import math
import re
import struct
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import boto3

from cache_processor.semantic_cache import (
    INDEX_NAME,
    KEY_PREFIX,
    VECTOR_DIM,
    normalize_question,
    question_hash,
)
from common import config as runtime_config
from common.models import IncomingMessage
from common.schema import CreatorProfile
from knowledge_setup.bulk_ingest_creators import (
    PreparedCreator,
    discover_creator_folders,
    iter_creator_files,
    load_creator_file,
    load_kb_setup_config,
    normalize_creator_id,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "simulator_question_prewarm.json"
DEFAULT_REPORT = REPO_ROOT / "simulator_question_prewarm_report.json"
DEFAULT_REPORTS_ROOT = REPO_ROOT / "reports" / "simulator-runs"

EXPECTED_SEMANTIC = "semantic_cache"
EXPECTED_EXACT = "exact_cache"
EXPECTED_FULL_MISS = "full_miss"
REQUIRED_SIMULATOR_FIELDS = {
    "message_id",
    "lead_id",
    "tenant_id",
    "user_id",
    "question_text",
    "timestamp",
    "correlation_id",
    "run_id",
    "expected_route",
    "question_type",
}


def default_validation_fallback_model_ids() -> list[str]:
    return dedupe_preserve_order(
        [
            runtime_config.BEDROCK_HAIKU_MODEL_ID,
            runtime_config.BEDROCK_SONNET_MODEL_ID,
            runtime_config._env(  # type: ignore[attr-defined]
                "BEDROCK_OPUS_MODEL_ID",
                "us.anthropic.claude-opus-4-1-20250805-v1:0",
            ),
        ]
    )


def worker_label() -> str:
    thread = threading.current_thread()
    return thread.name


@dataclass(frozen=True)
class PrewarmConfig:
    simulator_generation_strategy: str = "runtime_cache_build"
    cache_build_mode: str = "runtime"
    questions_per_creator: int = 100
    semantic_seed_count: int = 70
    exact_seed_count: int = 10
    full_miss_count: int = 20
    runtime_base_question_count: int = 20
    runtime_exact_duplicate_count: int = 10
    runtime_semantic_seed_count: int = 7
    runtime_paraphrases_per_seed: int = 10
    runtime_unique_miss_count: int = 12
    runtime_nova_retry_attempts: int = 1
    generation_batch_size: int = 10
    generation_model_id: str = "us.amazon.nova-lite-v1:0"
    generation_fallback_model_ids: list[str] = field(default_factory=lambda: ["amazon.nova-lite-v1:0"])
    validation_fallback_model_id: str = runtime_config.BEDROCK_HAIKU_MODEL_ID
    validation_fallback_model_ids: list[str] = field(default_factory=default_validation_fallback_model_ids)
    runtime_retry_until_success: bool = True
    runtime_retry_sleep_seconds: float = 2.0
    max_creator_repair_attempts: int = 5
    s3_records_per_batch: int = 1000
    sagemaker_embedding_batch_size: int = 128
    semantic_min_similarity: float = 0.92
    full_miss_max_similarity: float = 0.82
    exact_cache_table: str = runtime_config.CACHE_TABLE
    results_table: str = runtime_config.RESULTS_TABLE
    results_gsi: str = "run-id-processed-at"
    sagemaker_endpoint_name: str = runtime_config.SAGEMAKER_ENDPOINT_NAME
    s3_output_prefix: str = "s3://linkme-ai-poc-input-messages-095128162384/messages/{RUN_ID}/"
    timestamp: str = "2026-04-28T00:00:00Z"

    def validate(self) -> None:
        if self.simulator_generation_strategy not in {"preseeded_cache", "runtime_cache_build"}:
            raise ValueError("simulator_generation_strategy must be preseeded_cache or runtime_cache_build")
        if self.cache_build_mode not in {"preseed", "runtime"}:
            raise ValueError("cache_build_mode must be preseed or runtime")
        total = self.semantic_seed_count + self.exact_seed_count + self.full_miss_count
        if total != self.questions_per_creator:
            raise ValueError(
                "semantic_seed_count + exact_seed_count + full_miss_count must equal "
                f"questions_per_creator ({total} != {self.questions_per_creator})"
            )
        if self.semantic_seed_count <= 0 or self.exact_seed_count <= 0 or self.full_miss_count <= 0:
            raise ValueError("all route group counts must be positive")
        runtime_total = (
            self.runtime_base_question_count
            + self.runtime_exact_duplicate_count
            + self.runtime_semantic_seed_count * self.runtime_paraphrases_per_seed
        )
        if runtime_total != self.questions_per_creator:
            raise ValueError(
                "runtime_base_question_count + runtime_exact_duplicate_count + "
                "runtime_semantic_seed_count * runtime_paraphrases_per_seed must equal "
                f"questions_per_creator ({runtime_total} != {self.questions_per_creator})"
            )
        if self.runtime_base_question_count != self.full_miss_count:
            raise ValueError("runtime_base_question_count must match full_miss_count")
        if self.runtime_exact_duplicate_count != self.exact_seed_count:
            raise ValueError("runtime_exact_duplicate_count must match exact_seed_count")
        if self.runtime_semantic_seed_count * self.runtime_paraphrases_per_seed != self.semantic_seed_count:
            raise ValueError("runtime semantic groups must match semantic_seed_count")
        if (
            1 + self.runtime_semantic_seed_count + self.runtime_unique_miss_count
            != self.runtime_base_question_count
        ):
            raise ValueError("exact seed + semantic seeds + unique miss count must match runtime base count")
        if self.runtime_nova_retry_attempts < 0:
            raise ValueError("runtime_nova_retry_attempts must be non-negative")
        if self.generation_batch_size <= 0:
            raise ValueError("generation_batch_size must be positive")
        if not self.generation_model_id:
            raise ValueError("generation_model_id is required")
        if self.runtime_retry_sleep_seconds < 0:
            raise ValueError("runtime_retry_sleep_seconds must be non-negative")
        if self.max_creator_repair_attempts < 0:
            raise ValueError("max_creator_repair_attempts must be non-negative")
        if self.s3_records_per_batch <= 0:
            raise ValueError("s3_records_per_batch must be positive")
        if self.sagemaker_embedding_batch_size <= 0:
            raise ValueError("sagemaker_embedding_batch_size must be positive")


@dataclass(frozen=True)
class SemanticPair:
    base_question: str
    paraphrase: str
    answer: str


@dataclass(frozen=True)
class ExactSeed:
    question: str
    answer: str


@dataclass(frozen=True)
class FullMissQuestion:
    question: str


@dataclass
class CreatorQuestionSet:
    creator_id: str
    semantic_pairs: list[SemanticPair] = field(default_factory=list)
    exact_seeds: list[ExactSeed] = field(default_factory=list)
    full_miss_questions: list[FullMissQuestion] = field(default_factory=list)

    @property
    def simulator_question_count(self) -> int:
        return (
            len(self.semantic_pairs)
            + len(self.exact_seeds)
            + len(self.full_miss_questions)
        )

    @property
    def total_generated_text_count(self) -> int:
        return len(self.semantic_pairs) * 2 + len(self.exact_seeds) + len(self.full_miss_questions)


@dataclass(frozen=True)
class RuntimeSemanticGroup:
    group_id: str
    seed_question: str
    paraphrases: list[str]


@dataclass
class RuntimeQuestionSet:
    creator_id: str
    base_questions: list[str]
    exact_seed_question: str
    exact_duplicates: list[str]
    semantic_groups: list[RuntimeSemanticGroup]
    unique_miss_questions: list[str]
    moved_to_unique_questions: list[str] = field(default_factory=list)

    @property
    def simulator_question_count(self) -> int:
        return (
            len(self.base_questions)
            + len(self.exact_duplicates)
            + sum(len(group.paraphrases) for group in self.semantic_groups)
        )

    @property
    def total_generated_text_count(self) -> int:
        return self.simulator_question_count


class LlmClient(Protocol):
    def generate_json(self, prompt: str, *, max_tokens: int) -> dict[str, Any]:
        ...


class Embedder(Protocol):
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        ...


class PrewarmWriter(Protocol):
    def seed_exact_cache(self, tenant_id: str, question: str, answer: str, run_id: str) -> None:
        ...

    def seed_semantic_cache(
        self,
        tenant_id: str,
        question: str,
        answer: str,
        embedding: list[float],
        run_id: str,
    ) -> None:
        ...

    def upload_jsonl(self, bucket: str, key: str, records: list[dict[str, Any]]) -> None:
        ...

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        ...

    def read_text(self, bucket: str, key: str) -> str:
        ...


class BedrockJsonClient:
    def __init__(
        self,
        *,
        session: boto3.Session,
        model_id: str,
        fallback_model_ids: list[str] | None = None,
    ) -> None:
        self._client = session.client("bedrock-runtime")
        self._model_ids = [model_id] + list(fallback_model_ids or [])
        self.calls = 0
        self._lock = threading.Lock()
        self.token_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "unavailable": False,
        }

    def generate_json(self, prompt: str, *, max_tokens: int) -> dict[str, Any]:
        last_exc: Exception | None = None
        for model_id in self._model_ids:
            for attempt in range(1, 4):
                try:
                    response = self._client.converse(
                        modelId=model_id,
                        messages=[{"role": "user", "content": [{"text": prompt}]}],
                        inferenceConfig={
                            "maxTokens": max_tokens,
                            "temperature": 0.2,
                        },
                    )
                    with self._lock:
                        self.calls += 1
                        usage = response.get("usage")
                        if isinstance(usage, dict):
                            input_tokens = int(usage.get("inputTokens", 0))
                            output_tokens = int(usage.get("outputTokens", 0))
                            total_tokens = int(usage.get("totalTokens", input_tokens + output_tokens))
                            self.token_usage["input_tokens"] += input_tokens
                            self.token_usage["output_tokens"] += output_tokens
                            self.token_usage["total_tokens"] += total_tokens
                        else:
                            self.token_usage["unavailable"] = True
                    content = response.get("output", {}).get("message", {}).get("content", [])
                    text = "".join(block.get("text", "") for block in content if isinstance(block, dict))
                    return parse_json_object(text)
                except Exception as exc:
                    last_exc = exc
                    if attempt < 3 and is_retryable_aws_error(exc):
                        sleep_seconds = min(2 ** (attempt - 1), 8)
                        logger.warning(
                            "Bedrock generation retryable failure model=%s attempt=%s sleep=%ss error=%s",
                            model_id,
                            attempt,
                            sleep_seconds,
                            exc,
                        )
                        time.sleep(sleep_seconds)
                        continue
                    logger.warning("Bedrock generation failed with %s; trying fallback if configured", model_id)
                    break
        if last_exc:
            raise last_exc
        raise RuntimeError("No generation model IDs configured")


class SageMakerEmbedder:
    def __init__(self, *, session: boto3.Session, endpoint_name: str, batch_size: int = 128) -> None:
        self._client = session.client("sagemaker-runtime")
        self._endpoint_name = endpoint_name
        self._batch_size = batch_size
        self.calls = 0
        self._lock = threading.Lock()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings: list[list[float]] = []
        for index in range(0, len(texts), self._batch_size):
            chunk = texts[index:index + self._batch_size]
            response = self._client.invoke_endpoint(
                EndpointName=self._endpoint_name,
                ContentType="application/json",
                Body=json.dumps({"inputs": chunk}).encode("utf-8"),
            )
            with self._lock:
                self.calls += 1
            result = json.loads(response["Body"].read().decode("utf-8"))
            if not isinstance(result, list) or (result and not isinstance(result[0], list)):
                raise ValueError(f"Unexpected SageMaker embedding response shape: {type(result)}")
            embeddings.extend(result)
        return embeddings


class AwsPrewarmWriter:
    def __init__(
        self,
        *,
        session: boto3.Session,
        exact_cache_table: str,
        memorydb_endpoint: str,
        memorydb_port: int,
    ) -> None:
        self._ddb = session.resource("dynamodb")
        self._s3 = session.client("s3")
        self._exact_table_name = exact_cache_table
        self._redis = None
        self._memorydb_endpoint = memorydb_endpoint
        self._memorydb_port = memorydb_port
        self._index_ready = False

    def seed_exact_cache(self, tenant_id: str, question: str, answer: str, run_id: str) -> None:
        q_hash = question_hash(normalize_question(question))
        table = self._ddb.Table(self._exact_table_name)
        table.put_item(
            Item={
                "pk": f"{tenant_id}#{q_hash}",
                "tenant_id": tenant_id,
                "question": question,
                "answer": answer,
                "seed_source": "simulator_prewarm",
                "run_id": run_id,
                "seeded_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def seed_semantic_cache(
        self,
        tenant_id: str,
        question: str,
        answer: str,
        embedding: list[float],
        run_id: str,
    ) -> None:
        redis_client = self._get_redis()
        self._ensure_index(redis_client)
        q_hash = question_hash(normalize_question(question))
        redis_client.hset(
            f"{KEY_PREFIX}{tenant_id}:{q_hash}",
            mapping={
                "tenant_id": tenant_id,
                "question": question,
                "answer": answer,
                "seed_source": "simulator_prewarm",
                "run_id": run_id,
                "seeded_at": datetime.now(timezone.utc).isoformat(),
                "vector": pack_vector(embedding),
            },
        )

    def upload_jsonl(self, bucket: str, key: str, records: list[dict[str, Any]]) -> None:
        body = "".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            for record in records
        )
        self._s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/x-ndjson",
        )

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return keys

    def read_text(self, bucket: str, key: str) -> str:
        response = self._s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read().decode("utf-8")

    def _get_redis(self):  # type: ignore[no-untyped-def]
        if not self._memorydb_endpoint:
            raise RuntimeError("MEMORYDB_ENDPOINT or --memorydb-endpoint is required")
        if self._redis is None:
            import redis as redis_lib

            self._redis = redis_lib.Redis(
                host=self._memorydb_endpoint,
                port=self._memorydb_port,
                decode_responses=False,
                ssl=True,
            )
        return self._redis

    def _ensure_index(self, redis_client) -> None:  # type: ignore[no-untyped-def]
        if self._index_ready:
            return
        try:
            redis_client.execute_command(
                "FT.CREATE", INDEX_NAME,
                "ON", "HASH",
                "PREFIX", "1", KEY_PREFIX,
                "SCHEMA",
                "tenant_id", "TAG",
                "question", "TEXT",
                "answer", "TEXT",
                "vector", "VECTOR", "HNSW", "6",
                "TYPE", "FLOAT32",
                "DIM", str(VECTOR_DIM),
                "DISTANCE_METRIC", "COSINE",
            )
        except Exception as exc:
            lowered = str(exc).lower()
            if "already exists" not in lowered and "index already" not in lowered:
                raise
        self._index_ready = True


class NoopPrewarmWriter:
    def __init__(
        self,
        existing_keys: list[str] | None = None,
        existing_objects: dict[str, str] | None = None,
    ) -> None:
        self.exact: list[tuple[str, str, str]] = []
        self.semantic: list[tuple[str, str, str, list[float]]] = []
        self.uploads: list[tuple[str, str, int]] = []
        self.objects = dict(existing_objects or {})
        self.existing_keys = list(existing_keys or self.objects.keys())
        self._lock = threading.Lock()

    def seed_exact_cache(self, tenant_id: str, question: str, answer: str, run_id: str) -> None:
        with self._lock:
            self.exact.append((tenant_id, question, answer))

    def seed_semantic_cache(
        self,
        tenant_id: str,
        question: str,
        answer: str,
        embedding: list[float],
        run_id: str,
    ) -> None:
        with self._lock:
            self.semantic.append((tenant_id, question, answer, embedding))

    def upload_jsonl(self, bucket: str, key: str, records: list[dict[str, Any]]) -> None:
        body = "".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            for record in records
        )
        with self._lock:
            self.uploads.append((bucket, key, len(records)))
            self.objects[key] = body

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        with self._lock:
            uploaded = [key for _, key, _ in self.uploads]
            keys = dedupe_preserve_order([*self.existing_keys, *uploaded])
        return [key for key in keys if key.startswith(prefix)]

    def read_text(self, bucket: str, key: str) -> str:
        with self._lock:
            return self.objects[key]


def load_prewarm_config(path: Path) -> PrewarmConfig:
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if "bedrock_generation_batch_size" in raw and "generation_batch_size" not in raw:
        raw["generation_batch_size"] = raw["bedrock_generation_batch_size"]
    raw.pop("bedrock_generation_batch_size", None)
    if "bedrock_model" in raw and "generation_model_id" not in raw:
        legacy = str(raw["bedrock_model"])
        if legacy == "sonnet":
            raw["generation_model_id"] = runtime_config.BEDROCK_SONNET_MODEL_ID
        elif legacy == "haiku":
            raw["generation_model_id"] = runtime_config.BEDROCK_HAIKU_MODEL_ID
        else:
            raw["generation_model_id"] = legacy
    raw.pop("bedrock_model", None)
    cfg = PrewarmConfig(**raw)
    cfg.validate()
    return cfg


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Bedrock response must be a JSON object")
    return parsed


def pack_vector(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions differ")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def s3_prefix_parts(prefix: str, run_id: str) -> tuple[str, str]:
    rendered = prefix.replace("{RUN_ID}", run_id).replace("{run_id}", run_id)
    match = re.fullmatch(r"s3://([^/]+)/?(.*)", rendered)
    if not match:
        raise ValueError(f"s3_output_prefix must be an s3:// URI, got {prefix}")
    bucket = match.group(1)
    key_prefix = match.group(2)
    if key_prefix and not key_prefix.endswith("/"):
        key_prefix += "/"
    return bucket, key_prefix


def creator_context(creator: PreparedCreator, max_chars: int = 12000) -> str:
    profile = creator.profile
    rules = "\n".join(f"- {rule}" for rule in profile.agent.response_rules)
    doc_parts = []
    for doc in profile.knowledge_base.documents:
        source = getattr(doc, "source", "") or ""
        doc_parts.append(f"Document {doc.doc_id} ({doc.type}) {doc.name}: {source}")
    text = "\n\n".join(
        [
            f"Creator ID: {profile.creator.creator_id}",
            f"Creator name: {profile.creator.creator_name}",
            f"Main goal: {profile.agent.main_goal}",
            f"Tone: {profile.agent.tone.preset}",
            f"Out of scope reply: {profile.agent.out_of_scope_reply}",
            f"Response rules:\n{rules or '- none'}",
            "Available source/profile text:",
            "\n".join(doc_parts),
        ]
    )
    return text[:max_chars]


def creator_focus_terms(profile: CreatorProfile) -> list[str]:
    text_parts = [
        profile.creator.creator_name,
        profile.agent.main_goal,
        " ".join(profile.agent.response_rules),
    ]
    for doc in profile.knowledge_base.documents:
        text_parts.append(getattr(doc, "source", "") or "")
        text_parts.append(doc.name)
    text = " ".join(text_parts)
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9+'-]*(?:\s+[A-Za-z][A-Za-z0-9+'-]*){0,3}", text)
    blocked = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "his",
        "her",
        "their",
        "creator",
        "fans",
    }
    terms: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = " ".join(word.strip("-'").lower() for word in candidate.split())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) < 4:
            continue
        if cleaned in blocked or cleaned in seen:
            continue
        if all(part in blocked for part in cleaned.split()):
            continue
        seen.add(cleaned)
        terms.append(cleaned)
    defaults = [
        profile.agent.main_goal,
        profile.agent.tone.preset,
        "public creator profile",
        "fan conversations",
        "knowledge base content",
    ]
    for default in defaults:
        cleaned = re.sub(r"\s+", " ", default.lower()).strip()
        if cleaned and cleaned not in seen:
            terms.append(cleaned)
            seen.add(cleaned)
    return terms or [profile.creator.creator_name.lower()]


def repair_questions(
    creator: PreparedCreator,
    *,
    semantic_needed: int,
    exact_needed: int,
    full_needed: int,
    seen_questions: set[str],
) -> tuple[list[SemanticPair], list[ExactSeed], list[FullMissQuestion]]:
    """Fill rare model shortfalls with creator-specific template questions.

    The LLM remains the primary generator. This is a bounded safety valve for
    cheap models that return valid JSON but repeat themselves across batches.
    """
    name = creator.profile.creator.creator_name
    terms = creator_focus_terms(creator.profile)
    semantic_templates = [
        ("What should fans know about {name}'s {term}?", "Can you summarize {name}'s connection to {term}?"),
        ("How is {name} associated with {term}?", "What role does {term} play in {name}'s public work?"),
        ("What makes {term} relevant to {name}'s profile?", "Why would fans connect {name} with {term}?"),
        ("How would you describe {name}'s work around {term}?", "What is the short version of {name}'s link to {term}?"),
    ]
    exact_templates = [
        "What is one confirmed profile detail about {name} related to {term}?",
        "Which part of {name}'s public work connects to {term}?",
        "What can fans ask {name}'s assistant about {term}?",
    ]
    full_templates = [
        "What is a less common fan question about {name}'s audience and {term}?",
        "How might someone ask about {name}'s public image beyond {term}?",
        "What broader context could a fan request about {name} and {term}?",
    ]

    semantic: list[SemanticPair] = []
    exact: list[ExactSeed] = []
    full: list[FullMissQuestion] = []
    index = 0
    while len(semantic) < semantic_needed and index < semantic_needed * 20 + 100:
        term = terms[index % len(terms)]
        template = semantic_templates[index % len(semantic_templates)]
        base = template[0].format(name=name, term=term)
        paraphrase = template[1].format(name=name, term=term)
        paraphrase = tight_semantic_paraphrase(base, paraphrase)
        keys = {normalize_question(base), normalize_question(paraphrase)}
        if not keys & seen_questions and len(keys) == 2:
            semantic.append(
                SemanticPair(
                    base_question=base,
                    paraphrase=paraphrase,
                    answer=f"{name}'s profile connects this topic to {term} in their public creator work.",
                )
            )
            seen_questions.update(keys)
        index += 1

    index = 0
    while len(exact) < exact_needed and index < exact_needed * 20 + 100:
        term = terms[(index + len(semantic)) % len(terms)]
        question = exact_templates[index % len(exact_templates)].format(name=name, term=term)
        key = normalize_question(question)
        if key not in seen_questions:
            exact.append(
                ExactSeed(
                    question=question,
                    answer=f"{name}'s prepared profile includes {term} as part of the creator context.",
                )
            )
            seen_questions.add(key)
        index += 1

    index = 0
    while len(full) < full_needed and index < full_needed * 20 + 100:
        term = terms[(index + len(semantic) + len(exact)) % len(terms)]
        question = full_templates[index % len(full_templates)].format(name=name, term=term)
        key = normalize_question(question)
        if key not in seen_questions:
            full.append(FullMissQuestion(question=question))
            seen_questions.add(key)
        index += 1
    return semantic, exact, full


def distant_full_miss_questions(
    creator: PreparedCreator,
    *,
    count: int,
    seen_questions: set[str],
) -> list[FullMissQuestion]:
    name = creator.profile.creator.creator_name
    rule_terms = [re.sub(r"\s+", " ", rule.strip(". ")) for rule in creator.profile.agent.response_rules]
    topics = rule_terms + [
        "private relationships beyond public information",
        "unannounced TV projects",
        "political party endorsements",
        "rumors not covered in the public profile",
        "questions outside the creator's public work",
        "personal details the creator has not shared publicly",
        "unsupported claims about upcoming media appearances",
        "off-topic requests unrelated to the prepared creator profile",
        f"{name}'s private home address",
        f"{name}'s private phone number",
        f"{name}'s non-public family details",
        f"{name}'s confidential schedule",
        f"{name}'s private financial information",
        f"{name}'s medical information",
        f"a secret contract involving {name}",
        f"a rumor about {name} that is not in the profile",
    ]
    templates = [
        "Can {name} confirm details about {topic}?",
        "How should the assistant respond if a fan asks about {topic}?",
        "Is it okay to ask {name}'s assistant for {topic}?",
        "What should the assistant say when someone asks {name} about {topic}?",
        "Would {name}'s assistant answer a request involving {topic}?",
        "Should the assistant refuse to answer a question about {topic}?",
        "Can this chat verify a claim about {topic}?",
        "What boundary applies if someone asks about {topic}?",
    ]
    questions: list[FullMissQuestion] = []
    index = 0
    while len(questions) < count and index < count * 30 + 100:
        topic = topics[index % len(topics)]
        template = templates[index % len(templates)]
        question = template.format(name=name, topic=topic)
        key = normalize_question(question)
        if key not in seen_questions:
            questions.append(FullMissQuestion(question=question))
            seen_questions.add(key)
        index += 1
    if len(questions) != count:
        raise ValueError(f"{creator.tenant_id}: could not build {count} distant full-miss questions")
    return questions


def repair_full_miss_by_similarity(
    creator: PreparedCreator,
    qset: CreatorQuestionSet,
    cfg: PrewarmConfig,
    embedder: Embedder,
) -> tuple[list[FullMissQuestion], list[float]]:
    seed_texts = [pair.base_question for pair in qset.semantic_pairs] + [
        seed.question for seed in qset.exact_seeds
    ]
    seen = {
        normalize_question(text)
        for text in seed_texts
    }
    candidates = distant_full_miss_questions(
        creator,
        count=max(cfg.full_miss_count * 5, 80),
        seen_questions=set(seen),
    )
    candidate_texts = [candidate.question for candidate in candidates]
    vectors = embedder.embed_batch(seed_texts + candidate_texts)
    seed_vecs = vectors[:len(seed_texts)]
    candidate_vecs = vectors[len(seed_texts):]
    scored = []
    for candidate, vector in zip(candidates, candidate_vecs):
        max_score = max((cosine_similarity(vector, seed_vec) for seed_vec in seed_vecs), default=0.0)
        scored.append((max_score, candidate))
    selected = [
        (score, candidate)
        for score, candidate in sorted(scored, key=lambda item: item[0])
        if score < cfg.full_miss_max_similarity
    ][: cfg.full_miss_count]
    if len(selected) != cfg.full_miss_count:
        best = [round(score, 4) for score, _ in sorted(scored, key=lambda item: item[0])[:10]]
        raise ValueError(
            f"{creator.tenant_id}: only {len(selected)} distant full-miss candidates below "
            f"{cfg.full_miss_max_similarity}; best_scores={best}"
        )
    return [candidate for _, candidate in selected], [score for score, _ in selected]


def build_generation_prompt(
    *,
    profile: CreatorProfile,
    context: str,
    semantic_count: int,
    exact_count: int,
    full_miss_count: int,
    avoid_questions: list[str] | None = None,
) -> str:
    avoid_block = ""
    if avoid_questions:
        avoid_lines = "\n".join(f"- {question}" for question in avoid_questions[-80:])
        avoid_block = f"""

Do not repeat or closely paraphrase any of these already generated questions:
{avoid_lines}
""".rstrip()
    return f"""
Generate simulator test questions for this creator only.

Creator:
{context}
{avoid_block}

Return strict JSON only, with this shape:
{{
  "semantic_pairs": [
    {{"base_question": "...", "paraphrase": "...", "answer": "..."}}
  ],
  "exact_questions": [
    {{"question": "...", "answer": "..."}}
  ],
  "full_miss_questions": [
    {{"question": "..."}}
  ]
}}

Rules:
- Produce exactly {semantic_count} semantic_pairs, {exact_count} exact_questions,
  and {full_miss_count} full_miss_questions.
- This is one small batch in a larger run. Prefer narrow, varied angles over
  generic wording, and avoid asking the same kind of question twice.
- Every question must be specific to {profile.creator.creator_name}.
- Semantic pair paraphrases must ask the same thing as the base question while
  using meaningfully different wording. Do not make exact text matches.
- Exact questions should be useful standalone fan questions with answers.
- Full miss questions must not be close duplicates of any semantic or exact
  seeded question.
- Answers are cache seed answers, 1-3 concise sentences, grounded in the
  provided creator profile/source text. Do not invent private facts.
- Use plain question text only; no numbering prefixes.
""".strip()


def build_runtime_base_prompt(*, profile: CreatorProfile, context: str, count: int) -> str:
    return f"""
Generate {count} distinct simulator seed questions for this creator.

Creator:
{context}

Return strict JSON only:
{{"base_questions":["..."]}}

Rules:
- Each question must be specific to {profile.creator.creator_name}.
- Questions must be mutually distinct and cover different facts, topics, or boundaries from the profile.
- Avoid paraphrases of the same question.
- Keep questions concise and natural, with no numbering prefixes.
- Do not invent private facts.
""".strip()


def build_runtime_paraphrase_prompt(
    *,
    profile: CreatorProfile,
    context: str,
    seed_question: str,
    count: int,
    avoid_questions: list[str],
) -> str:
    avoid_block = "\n".join(f"- {question}" for question in avoid_questions[-80:])
    return f"""
Generate {count} paraphrases of exactly this seed question:
{seed_question}

Creator:
{context}

Avoid these existing questions:
{avoid_block}

Return strict JSON only:
{{"paraphrases":["..."]}}

Rules:
- Every paraphrase must ask the same thing as the seed question.
- Every paraphrase must be semantically very close to the seed for semantic-cache matching.
- No paraphrase may be byte-for-byte identical to the seed or to another paraphrase.
- Use plain question text only; no numbering prefixes.
- Keep the creator-specific meaning intact.
""".strip()


def coerce_string_list(raw: dict[str, Any], key: str) -> list[str]:
    values = raw.get(key, [])
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_question(str(value))
        normalized = normalize_question(text)
        if text and normalized not in seen:
            cleaned.append(text)
            seen.add(normalized)
    return cleaned


def select_distinct_questions(
    *,
    questions: list[str],
    count: int,
    embedder: Embedder,
    max_similarity: float,
) -> tuple[list[str], list[list[float]], list[dict[str, Any]]]:
    if not questions:
        return [], [], []
    vectors = embedder.embed_batch(questions)
    selected: list[str] = []
    selected_vectors: list[list[float]] = []
    rejected: list[dict[str, Any]] = []
    for question, vector in zip(questions, vectors):
        if len(selected) >= count:
            break
        max_score = max((cosine_similarity(vector, other) for other in selected_vectors), default=0.0)
        if max_score < max_similarity:
            selected.append(question)
            selected_vectors.append(vector)
        else:
            rejected.append({"question": question, "max_similarity": round(max_score, 6)})
    return selected, selected_vectors, rejected


def deterministic_base_question_candidates(creator: PreparedCreator, count: int) -> list[str]:
    name = creator.profile.creator.creator_name
    terms = creator_focus_terms(creator.profile)
    templates = [
        "What should fans know about {name}'s work with {term}?",
        "How does {term} show up in {name}'s public profile?",
        "What is one useful fact about {name} related to {term}?",
        "Why might fans ask {name}'s assistant about {term}?",
        "What boundary should the assistant follow for {name} when discussing {term}?",
        "What public context connects {name} with {term}?",
        "How would {name}'s assistant summarize {term}?",
        "What can someone learn from {name}'s profile about {term}?",
    ]
    questions: list[str] = []
    seen: set[str] = set()
    index = 0
    while len(questions) < count and index < count * 40 + 100:
        term = terms[index % len(terms)]
        template = templates[index % len(templates)]
        question = template.format(name=name, term=term)
        key = normalize_question(question)
        if key not in seen:
            seen.add(key)
            questions.append(question)
        index += 1
    return questions


def runtime_paraphrase_variants(seed_question: str) -> list[str]:
    seed = clean_question(seed_question)
    body = seed[:-1] if seed.endswith("?") else seed
    lower_body = body[:1].lower() + body[1:] if body else body
    return [
        f"{body}, please?",
        f"{body} in brief?",
        f"{body} for fans?",
        f"Can you answer this: {lower_body}?",
        f"Please explain: {lower_body}?",
        f"Could you summarize: {lower_body}?",
        f"What is the short answer to: {lower_body}?",
        f"For this creator, {lower_body}?",
        f"Can you tell me: {lower_body}?",
        f"Could you cover: {lower_body}?",
        f"Please answer briefly: {lower_body}?",
        f"In simple terms, {lower_body}?",
        f"For a fan, {lower_body}?",
        f"What should I know about this: {lower_body}?",
    ]


def coerce_question_set(
    raw: dict[str, Any],
    creator_id: str,
    cfg: PrewarmConfig,
    *,
    semantic_count: int | None = None,
    exact_count: int | None = None,
    full_miss_count: int | None = None,
    allow_short: bool = False,
) -> CreatorQuestionSet:
    expected_semantic = cfg.semantic_seed_count if semantic_count is None else semantic_count
    expected_exact = cfg.exact_seed_count if exact_count is None else exact_count
    expected_full = cfg.full_miss_count if full_miss_count is None else full_miss_count
    semantic_pairs = [
        SemanticPair(
            base_question=clean_question(item.get("base_question", "")),
            paraphrase=tight_semantic_paraphrase(
                item.get("base_question", ""),
                item.get("paraphrase", ""),
            ),
            answer=clean_answer(item.get("answer", "")),
        )
        for item in raw.get("semantic_pairs", [])
        if isinstance(item, dict)
    ]
    exact = [
        ExactSeed(
            question=clean_question(item.get("question", "")),
            answer=clean_answer(item.get("answer", "")),
        )
        for item in raw.get("exact_questions", [])
        if isinstance(item, dict)
    ]
    full = [
        FullMissQuestion(question=clean_question(item.get("question", "")))
        for item in raw.get("full_miss_questions", [])
        if isinstance(item, dict)
    ]
    qset = CreatorQuestionSet(
        creator_id=creator_id,
        semantic_pairs=semantic_pairs[:expected_semantic],
        exact_seeds=exact[:expected_exact],
        full_miss_questions=full[:expected_full],
    )
    if not allow_short:
        validate_counts(
            qset,
            cfg,
            semantic_count=expected_semantic,
            exact_count=expected_exact,
            full_miss_count=expected_full,
        )
    return qset


def clean_question(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = re.sub(r"^\d+[\).\-\s]+", "", text).strip()
    return text


def tight_semantic_paraphrase(base_question: str, proposed: str = "") -> str:
    """Return a non-exact paraphrase that stays very close in embedding space."""
    base = clean_question(base_question)
    proposed = clean_question(proposed)
    if proposed and normalize_question(proposed) != normalize_question(base):
        # Cheap generation models often drift too far for a 0.92 threshold, so
        # keep only very light edits when possible.
        proposed_words = set(normalize_question(proposed).split())
        base_words = set(normalize_question(base).split())
        overlap = len(proposed_words & base_words) / max(len(base_words), 1)
        if overlap >= 0.85:
            return proposed
    if base.endswith("?"):
        return f"{base[:-1]}, please?"
    return f"{base}, please?"


def force_tight_semantic_paraphrase(base_question: str, attempt: int = 0) -> str:
    base = clean_question(base_question)
    without_question = base[:-1] if base.endswith("?") else base
    variants = [
        f"{without_question}, please?",
        f"{without_question} in brief?",
        f"{without_question} for fans?",
        f"{without_question} again?",
        f"{without_question} in simple terms?",
    ]
    candidate = variants[attempt % len(variants)]
    if normalize_question(candidate) == normalize_question(base):
        return f"{without_question}, please?"
    return candidate


def clean_answer(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def validate_counts(
    qset: CreatorQuestionSet,
    cfg: PrewarmConfig,
    *,
    semantic_count: int | None = None,
    exact_count: int | None = None,
    full_miss_count: int | None = None,
) -> None:
    expected_semantic = cfg.semantic_seed_count if semantic_count is None else semantic_count
    expected_exact = cfg.exact_seed_count if exact_count is None else exact_count
    expected_full = cfg.full_miss_count if full_miss_count is None else full_miss_count
    expected_simulator_total = expected_semantic + expected_exact + expected_full
    expected_generated_total = expected_semantic * 2 + expected_exact + expected_full
    if len(qset.semantic_pairs) != expected_semantic:
        raise ValueError(f"{qset.creator_id}: expected {expected_semantic} semantic pairs")
    if len(qset.exact_seeds) != expected_exact:
        raise ValueError(f"{qset.creator_id}: expected {expected_exact} exact seeds")
    if len(qset.full_miss_questions) != expected_full:
        raise ValueError(f"{qset.creator_id}: expected {expected_full} full-miss questions")
    if qset.simulator_question_count != expected_simulator_total:
        raise ValueError(f"{qset.creator_id}: expected {expected_simulator_total} simulator questions")
    if qset.total_generated_text_count != expected_generated_total:
        raise ValueError(f"{qset.creator_id}: generated text total mismatch")


def validate_text_uniqueness(qset: CreatorQuestionSet) -> None:
    normalized: dict[str, str] = {}
    texts: list[str] = []
    for pair in qset.semantic_pairs:
        if not pair.base_question or not pair.paraphrase or not pair.answer:
            raise ValueError(f"{qset.creator_id}: empty semantic question or answer")
        if normalize_question(pair.base_question) == normalize_question(pair.paraphrase):
            raise ValueError(f"{qset.creator_id}: semantic paraphrase exactly matches base question")
        texts.extend([pair.base_question, pair.paraphrase])
    for item in qset.exact_seeds:
        if not item.question or not item.answer:
            raise ValueError(f"{qset.creator_id}: empty exact question or answer")
        texts.append(item.question)
    for item in qset.full_miss_questions:
        if not item.question:
            raise ValueError(f"{qset.creator_id}: empty full-miss question")
        texts.append(item.question)
    for text in texts:
        key = normalize_question(text)
        if key in normalized:
            raise ValueError(
                f"{qset.creator_id}: duplicate normalized question: {text!r} duplicates {normalized[key]!r}"
            )
        normalized[key] = text


def validate_embedding_similarity(
    qset: CreatorQuestionSet,
    cfg: PrewarmConfig,
    embedder: Embedder,
) -> dict[str, Any]:
    report = embedding_similarity_report(qset, cfg, embedder)
    bad_semantic = report["bad_semantic_indices"]
    if bad_semantic:
        semantic_scores = report["semantic_pair_scores"]
        raise ValueError(
            f"{qset.creator_id}: {len(bad_semantic)} semantic paraphrases below "
            f"{cfg.semantic_min_similarity}; first index={bad_semantic[0]} "
            f"score={semantic_scores[bad_semantic[0]]:.4f}"
        )

    bad_full = report["bad_full_miss_indices"]
    if bad_full:
        max_full_scores = report["full_miss_max_seed_scores"]
        raise ValueError(
            f"{qset.creator_id}: {len(bad_full)} full-miss questions too close to seeds; "
            f"first index={bad_full[0]} score={max_full_scores[bad_full[0]]:.4f}"
        )
    return report


def embedding_similarity_report(
    qset: CreatorQuestionSet,
    cfg: PrewarmConfig,
    embedder: Embedder,
) -> dict[str, Any]:
    semantic_base_texts = [pair.base_question for pair in qset.semantic_pairs]
    semantic_para_texts = [pair.paraphrase for pair in qset.semantic_pairs]
    exact_texts = [item.question for item in qset.exact_seeds]
    full_texts = [item.question for item in qset.full_miss_questions]
    all_texts = semantic_base_texts + semantic_para_texts + exact_texts + full_texts
    embeddings = embedder.embed_batch(all_texts)
    if len(embeddings) != len(all_texts):
        raise ValueError(f"{qset.creator_id}: embedding count mismatch")

    base_end = len(semantic_base_texts)
    para_end = base_end + len(semantic_para_texts)
    exact_end = para_end + len(exact_texts)
    base_vecs = embeddings[:base_end]
    para_vecs = embeddings[base_end:para_end]
    exact_vecs = embeddings[para_end:exact_end]
    full_vecs = embeddings[exact_end:]

    semantic_scores = [
        cosine_similarity(base_vec, para_vec)
        for base_vec, para_vec in zip(base_vecs, para_vecs)
    ]
    bad_semantic = [
        index
        for index, score in enumerate(semantic_scores)
        if score < cfg.semantic_min_similarity
    ]

    seed_vecs = base_vecs + exact_vecs
    max_full_scores = [
        max((cosine_similarity(full_vec, seed_vec) for seed_vec in seed_vecs), default=0.0)
        for full_vec in full_vecs
    ]
    bad_full = [
        index
        for index, score in enumerate(max_full_scores)
        if score >= cfg.full_miss_max_similarity
    ]

    return {
        "base_embeddings": base_vecs,
        "semantic_pair_scores": semantic_scores,
        "full_miss_max_seed_scores": max_full_scores,
        "bad_semantic_indices": bad_semantic,
        "bad_full_miss_indices": bad_full,
    }


def generate_creator_questions(
    creator: PreparedCreator,
    cfg: PrewarmConfig,
    llm: LlmClient,
    call_log: list[dict[str, Any]] | None = None,
) -> CreatorQuestionSet:
    context = creator_context(creator)
    semantic_pairs: list[SemanticPair] = []
    exact_seeds: list[ExactSeed] = []
    full_miss_questions: list[FullMissQuestion] = []
    seen_questions: set[str] = set()
    avoid_questions: list[str] = []
    repair_used = False
    batch_plan: list[tuple[int, int, int]] = []
    remaining_semantic = cfg.semantic_seed_count
    while remaining_semantic:
        count = min(cfg.generation_batch_size, remaining_semantic)
        batch_plan.append((count, 0, 0))
        remaining_semantic -= count
    remaining_exact = cfg.exact_seed_count
    while remaining_exact:
        count = min(cfg.generation_batch_size, remaining_exact)
        batch_plan.append((0, count, 0))
        remaining_exact -= count
    remaining_full = cfg.full_miss_count
    while remaining_full:
        count = min(cfg.generation_batch_size, remaining_full)
        batch_plan.append((0, 0, count))
        remaining_full -= count

    for semantic_count, exact_count, full_count in batch_plan:

        prompt = build_generation_prompt(
            profile=creator.profile,
            context=context,
            semantic_count=semantic_count,
            exact_count=exact_count,
            full_miss_count=full_count,
            avoid_questions=avoid_questions,
        )
        generated_items = semantic_count + exact_count + full_count
        t0 = time.perf_counter()
        max_tokens = max(3000, generated_items * 220)
        raw = llm.generate_json(prompt, max_tokens=max_tokens)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if call_log is not None:
            call_log.append(
                {
                    "creator_id": creator.tenant_id,
                    "semantic_pairs_requested": semantic_count,
                    "exact_questions_requested": exact_count,
                    "full_miss_questions_requested": full_count,
                    "max_tokens": max_tokens,
                    "elapsed_ms": round(elapsed_ms, 2),
                }
            )
        partial = coerce_question_set(
            raw,
            creator.tenant_id,
            cfg,
            semantic_count=semantic_count,
            exact_count=exact_count,
            full_miss_count=full_count,
            allow_short=True,
        )
        added_semantic = 0
        for pair in partial.semantic_pairs:
            if not pair.base_question or not pair.paraphrase or not pair.answer:
                continue
            base_key = normalize_question(pair.base_question)
            para_key = normalize_question(pair.paraphrase)
            if base_key in seen_questions or para_key in seen_questions or base_key == para_key:
                continue
            semantic_pairs.append(pair)
            seen_questions.update({base_key, para_key})
            avoid_questions.extend([pair.base_question, pair.paraphrase])
            added_semantic += 1
            if added_semantic >= semantic_count:
                break

        for seed in partial.exact_seeds:
            if not seed.question or not seed.answer:
                continue
            key = normalize_question(seed.question)
            if key in seen_questions:
                continue
            exact_seeds.append(seed)
            seen_questions.add(key)
            avoid_questions.append(seed.question)
            if len(exact_seeds) >= cfg.exact_seed_count:
                break

        for question in partial.full_miss_questions:
            if not question.question:
                continue
            key = normalize_question(question.question)
            if key in seen_questions:
                continue
            full_miss_questions.append(question)
            seen_questions.add(key)
            avoid_questions.append(question.question)
            if len(full_miss_questions) >= cfg.full_miss_count:
                break

    qset = CreatorQuestionSet(
        creator_id=creator.tenant_id,
        semantic_pairs=semantic_pairs,
        exact_seeds=exact_seeds,
        full_miss_questions=full_miss_questions,
    )
    local_call_log = call_log if call_log is not None else []
    repair_missing_questions_with_llm(creator, qset, cfg, llm, local_call_log)
    before_counts = (
        len(qset.semantic_pairs),
        len(qset.exact_seeds),
        len(qset.full_miss_questions),
    )
    deterministic_fill_missing_questions(creator, qset, cfg, local_call_log)
    after_counts = (
        len(qset.semantic_pairs),
        len(qset.exact_seeds),
        len(qset.full_miss_questions),
    )
    repair_used = before_counts != after_counts or any(
        entry.get("repair_attempt") or entry.get("deterministic_count_repair_used")
        for entry in local_call_log
    )
    validate_counts(qset, cfg)
    validate_text_uniqueness(qset)
    if repair_used:
        logger.warning("Used count repair to fill duplicate/short generation for %s", creator.tenant_id)
    return qset


def append_unique_partial_questions(
    qset: CreatorQuestionSet,
    partial: CreatorQuestionSet,
    *,
    seen_questions: set[str],
    cfg: PrewarmConfig,
) -> dict[str, int]:
    added = {"semantic": 0, "exact": 0, "full_miss": 0}
    for pair in partial.semantic_pairs:
        if len(qset.semantic_pairs) >= cfg.semantic_seed_count:
            break
        if not pair.base_question or not pair.paraphrase or not pair.answer:
            continue
        base_key = normalize_question(pair.base_question)
        para_key = normalize_question(pair.paraphrase)
        if base_key in seen_questions or para_key in seen_questions or base_key == para_key:
            continue
        qset.semantic_pairs.append(pair)
        seen_questions.update({base_key, para_key})
        added["semantic"] += 1

    for seed in partial.exact_seeds:
        if len(qset.exact_seeds) >= cfg.exact_seed_count:
            break
        if not seed.question or not seed.answer:
            continue
        key = normalize_question(seed.question)
        if key in seen_questions:
            continue
        qset.exact_seeds.append(seed)
        seen_questions.add(key)
        added["exact"] += 1

    for question in partial.full_miss_questions:
        if len(qset.full_miss_questions) >= cfg.full_miss_count:
            break
        if not question.question:
            continue
        key = normalize_question(question.question)
        if key in seen_questions:
            continue
        qset.full_miss_questions.append(question)
        seen_questions.add(key)
        added["full_miss"] += 1
    return added


def all_generated_questions(qset: CreatorQuestionSet) -> list[str]:
    return (
        [pair.base_question for pair in qset.semantic_pairs]
        + [pair.paraphrase for pair in qset.semantic_pairs]
        + [seed.question for seed in qset.exact_seeds]
        + [question.question for question in qset.full_miss_questions]
    )


def repair_missing_questions_with_llm(
    creator: PreparedCreator,
    qset: CreatorQuestionSet,
    cfg: PrewarmConfig,
    llm: LlmClient,
    call_log: list[dict[str, Any]],
) -> None:
    context = creator_context(creator)
    seen_questions = {normalize_question(question) for question in all_generated_questions(qset)}
    for attempt in range(1, cfg.max_creator_repair_attempts + 1):
        missing_semantic = cfg.semantic_seed_count - len(qset.semantic_pairs)
        missing_exact = cfg.exact_seed_count - len(qset.exact_seeds)
        missing_full = cfg.full_miss_count - len(qset.full_miss_questions)
        if missing_semantic <= 0 and missing_exact <= 0 and missing_full <= 0:
            return
        logger.warning(
            "Repair attempt %s/%s for %s missing semantic=%s exact=%s full_miss=%s",
            attempt,
            cfg.max_creator_repair_attempts,
            creator.tenant_id,
            max(missing_semantic, 0),
            max(missing_exact, 0),
            max(missing_full, 0),
        )
        plans = [
            (min(cfg.generation_batch_size, max(missing_semantic, 0)), 0, 0),
            (0, min(cfg.generation_batch_size, max(missing_exact, 0)), 0),
            (0, 0, min(cfg.generation_batch_size, max(missing_full, 0))),
        ]
        for semantic_count, exact_count, full_count in plans:
            if semantic_count == 0 and exact_count == 0 and full_count == 0:
                continue
            prompt = build_generation_prompt(
                profile=creator.profile,
                context=context,
                semantic_count=semantic_count,
                exact_count=exact_count,
                full_miss_count=full_count,
                avoid_questions=all_generated_questions(qset),
            )
            generated_items = semantic_count + exact_count + full_count
            t0 = time.perf_counter()
            raw = llm.generate_json(prompt, max_tokens=max(3000, generated_items * 240))
            elapsed_ms = (time.perf_counter() - t0) * 1000
            partial = coerce_question_set(
                raw,
                creator.tenant_id,
                cfg,
                semantic_count=semantic_count,
                exact_count=exact_count,
                full_miss_count=full_count,
                allow_short=True,
            )
            added = append_unique_partial_questions(qset, partial, seen_questions=seen_questions, cfg=cfg)
            call_log.append(
                {
                    "creator_id": creator.tenant_id,
                    "repair_attempt": attempt,
                    "semantic_pairs_requested": semantic_count,
                    "exact_questions_requested": exact_count,
                    "full_miss_questions_requested": full_count,
                    "semantic_pairs_added": added["semantic"],
                    "exact_questions_added": added["exact"],
                    "full_miss_questions_added": added["full_miss"],
                    "elapsed_ms": round(elapsed_ms, 2),
                }
            )


def deterministic_fill_missing_questions(
    creator: PreparedCreator,
    qset: CreatorQuestionSet,
    cfg: PrewarmConfig,
    call_log: list[dict[str, Any]],
) -> None:
    semantic_needed = cfg.semantic_seed_count - len(qset.semantic_pairs)
    exact_needed = cfg.exact_seed_count - len(qset.exact_seeds)
    full_needed = cfg.full_miss_count - len(qset.full_miss_questions)
    if semantic_needed <= 0 and exact_needed <= 0 and full_needed <= 0:
        return
    seen_questions = {normalize_question(question) for question in all_generated_questions(qset)}
    semantic_repair, exact_repair, full_repair = repair_questions(
        creator,
        semantic_needed=max(semantic_needed, 0),
        exact_needed=max(exact_needed, 0),
        full_needed=max(full_needed, 0),
        seen_questions=seen_questions,
    )
    qset.semantic_pairs.extend(semantic_repair)
    qset.exact_seeds.extend(exact_repair)
    qset.full_miss_questions.extend(full_repair)
    call_log.append(
        {
            "creator_id": creator.tenant_id,
            "deterministic_count_repair_used": True,
            "semantic_pairs_repaired": len(semantic_repair),
            "exact_questions_repaired": len(exact_repair),
            "full_miss_questions_repaired": len(full_repair),
        }
    )


def repair_low_similarity_semantic_paraphrases(
    qset: CreatorQuestionSet,
    bad_indices: list[int],
    *,
    attempt: int,
    call_log: list[dict[str, Any]],
) -> None:
    replacements = 0
    pairs = list(qset.semantic_pairs)
    for index in bad_indices:
        if index < 0 or index >= len(pairs):
            continue
        pair = pairs[index]
        replacement = force_tight_semantic_paraphrase(pair.base_question, attempt)
        if normalize_question(replacement) == normalize_question(pair.paraphrase):
            replacement = force_tight_semantic_paraphrase(pair.base_question, attempt + 1)
        pairs[index] = SemanticPair(
            base_question=pair.base_question,
            paraphrase=replacement,
            answer=pair.answer,
        )
        replacements += 1
    qset.semantic_pairs = pairs
    call_log.append(
        {
            "creator_id": qset.creator_id,
            "semantic_similarity_repair_attempt": attempt + 1,
            "bad_semantic_paraphrases": len(bad_indices),
            "semantic_paraphrases_replaced": replacements,
        }
    )


def validate_embedding_similarity_with_repairs(
    creator: PreparedCreator,
    qset: CreatorQuestionSet,
    cfg: PrewarmConfig,
    embedder: Embedder,
    call_log: list[dict[str, Any]],
) -> dict[str, Any]:
    last_report: dict[str, Any] | None = None
    for attempt in range(cfg.max_creator_repair_attempts + 1):
        report = embedding_similarity_report(qset, cfg, embedder)
        last_report = report
        bad_semantic = list(report["bad_semantic_indices"])
        bad_full = list(report["bad_full_miss_indices"])
        if not bad_semantic and not bad_full:
            return report
        if attempt >= cfg.max_creator_repair_attempts:
            break
        if bad_semantic:
            logger.warning(
                "Repairing %s low-similarity semantic paraphrases for %s (attempt %s/%s)",
                len(bad_semantic),
                creator.tenant_id,
                attempt + 1,
                cfg.max_creator_repair_attempts,
            )
            repair_low_similarity_semantic_paraphrases(
                qset,
                bad_semantic,
                attempt=attempt,
                call_log=call_log,
            )
            validate_text_uniqueness(qset)
            continue
        if bad_full:
            logger.warning(
                "Repairing %s full-miss questions too close to seeds for %s (attempt %s/%s)",
                len(bad_full),
                creator.tenant_id,
                attempt + 1,
                cfg.max_creator_repair_attempts,
            )
            repaired_full_miss, repaired_scores = repair_full_miss_by_similarity(
                creator,
                qset,
                cfg,
                embedder,
            )
            qset.full_miss_questions = repaired_full_miss
            validate_text_uniqueness(qset)
            call_log.append(
                {
                    "creator_id": creator.tenant_id,
                    "full_miss_repaired_for_similarity": True,
                    "full_miss_questions_repaired": cfg.full_miss_count,
                    "full_miss_repaired_max_similarity": round(max(repaired_scores), 6),
                    "repair_attempt": attempt + 1,
                }
            )
    if last_report is None:
        raise ValueError(f"{creator.tenant_id}: embedding validation did not run")
    if last_report["bad_semantic_indices"]:
        scores = last_report["semantic_pair_scores"]
        first = last_report["bad_semantic_indices"][0]
        raise ValueError(
            f"{creator.tenant_id}: {len(last_report['bad_semantic_indices'])} semantic paraphrases below "
            f"{cfg.semantic_min_similarity} after repair; first index={first} score={scores[first]:.4f}"
        )
    scores = last_report["full_miss_max_seed_scores"]
    first = last_report["bad_full_miss_indices"][0]
    raise ValueError(
        f"{creator.tenant_id}: {len(last_report['bad_full_miss_indices'])} full-miss questions too close "
        f"after repair; first index={first} score={scores[first]:.4f}"
    )


def generate_runtime_base_questions(
    creator: PreparedCreator,
    cfg: PrewarmConfig,
    llm: LlmClient,
    fallback_llm: LlmClient | None,
    embedder: Embedder,
    call_log: list[dict[str, Any]],
) -> tuple[list[str], int]:
    context = creator_context(creator)
    target = cfg.runtime_base_question_count
    attempts: list[tuple[str, LlmClient]] = [("nova_lite", llm)]
    for retry_index in range(cfg.runtime_nova_retry_attempts):
        attempts.append((f"nova_lite_retry_{retry_index + 1}", llm))
    if fallback_llm is not None:
        attempts.append(("haiku_fallback", fallback_llm))

    candidates: list[str] = []
    seen: set[str] = set()
    nova_retries = 0
    haiku_fallbacks = 0
    for attempt_name, model in attempts:
        if attempt_name.startswith("nova_lite_retry"):
            nova_retries += 1
        if attempt_name == "haiku_fallback":
            haiku_fallbacks += 1
        prompt = build_runtime_base_prompt(
            profile=creator.profile,
            context=context,
            count=target,
        )
        t0 = time.perf_counter()
        raw = model.generate_json(prompt, max_tokens=max(3500, target * 160))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        generated = coerce_string_list(raw, "base_questions")
        for question in generated:
            key = normalize_question(question)
            if key not in seen:
                seen.add(key)
                candidates.append(question)
        selected, _, rejected = select_distinct_questions(
            questions=candidates,
            count=target,
            embedder=embedder,
            max_similarity=cfg.semantic_min_similarity,
        )
        call_log.append(
            {
                "creator_id": creator.tenant_id,
                "runtime_base_generation_attempt": attempt_name,
                "base_questions_requested": target,
                "base_questions_generated": len(generated),
                "base_questions_candidates": len(candidates),
                "base_questions_selected": len(selected),
                "rejected_for_similarity": len(rejected),
                "elapsed_ms": round(elapsed_ms, 2),
            }
        )
        if len(selected) == target:
            return selected, haiku_fallbacks

    deterministic = deterministic_base_question_candidates(creator, target * 4)
    for question in deterministic:
        key = normalize_question(question)
        if key not in seen:
            seen.add(key)
            candidates.append(question)
    selected, _, rejected = select_distinct_questions(
        questions=candidates,
        count=target,
        embedder=embedder,
        max_similarity=cfg.semantic_min_similarity,
    )
    call_log.append(
        {
            "creator_id": creator.tenant_id,
            "runtime_base_deterministic_repair_used": True,
            "base_questions_candidates": len(candidates),
            "base_questions_selected": len(selected),
            "rejected_for_similarity": len(rejected),
        }
    )
    if len(selected) != target:
        raise ValueError(f"{creator.tenant_id}: could not build {target} distinct runtime base questions")
    return selected, haiku_fallbacks


def validate_runtime_question_set(
    qset: RuntimeQuestionSet,
    cfg: PrewarmConfig,
    embedder: Embedder,
) -> dict[str, Any]:
    if len(qset.base_questions) != cfg.runtime_base_question_count:
        raise ValueError(f"{qset.creator_id}: expected {cfg.runtime_base_question_count} runtime base questions")
    if len(qset.exact_duplicates) != cfg.runtime_exact_duplicate_count:
        raise ValueError(f"{qset.creator_id}: expected {cfg.runtime_exact_duplicate_count} exact duplicates")
    if len(qset.semantic_groups) != cfg.runtime_semantic_seed_count:
        raise ValueError(f"{qset.creator_id}: expected {cfg.runtime_semantic_seed_count} semantic groups")
    if any(len(group.paraphrases) != cfg.runtime_paraphrases_per_seed for group in qset.semantic_groups):
        raise ValueError(f"{qset.creator_id}: expected {cfg.runtime_paraphrases_per_seed} paraphrases per group")
    if len(qset.unique_miss_questions) != cfg.runtime_unique_miss_count:
        raise ValueError(f"{qset.creator_id}: expected {cfg.runtime_unique_miss_count} unique miss questions")
    if qset.simulator_question_count != cfg.questions_per_creator:
        raise ValueError(f"{qset.creator_id}: expected {cfg.questions_per_creator} runtime simulator questions")
    if any(duplicate != qset.exact_seed_question for duplicate in qset.exact_duplicates):
        raise ValueError(f"{qset.creator_id}: exact duplicates are not byte-for-byte identical")

    all_texts = (
        qset.base_questions
        + qset.exact_duplicates
        + [paraphrase for group in qset.semantic_groups for paraphrase in group.paraphrases]
    )
    normalized: dict[str, str] = {}
    for text in qset.base_questions + [p for group in qset.semantic_groups for p in group.paraphrases]:
        key = normalize_question(text)
        if key in normalized:
            raise ValueError(f"{qset.creator_id}: duplicate normalized runtime question {text!r}")
        normalized[key] = text

    base_vectors = embedder.embed_batch(qset.base_questions)
    base_pair_scores: list[float] = []
    for left in range(len(base_vectors)):
        for right in range(left + 1, len(base_vectors)):
            score = cosine_similarity(base_vectors[left], base_vectors[right])
            base_pair_scores.append(score)
            if score >= cfg.semantic_min_similarity:
                raise ValueError(
                    f"{qset.creator_id}: runtime base questions {left}/{right} too similar "
                    f"score={score:.4f}"
                )

    seed_index_by_question = {question: index for index, question in enumerate(qset.base_questions)}
    group_scores: list[float] = []
    cross_group_scores: list[float] = []
    failed_similarity: list[dict[str, Any]] = []
    for group in qset.semantic_groups:
        seed_index = seed_index_by_question[group.seed_question]
        paraphrase_vectors = embedder.embed_batch(group.paraphrases)
        for para_index, (paraphrase, vector) in enumerate(zip(group.paraphrases, paraphrase_vectors)):
            seed_score = cosine_similarity(base_vectors[seed_index], vector)
            group_scores.append(seed_score)
            if seed_score < cfg.semantic_min_similarity:
                failed_similarity.append(
                    {
                        "group_id": group.group_id,
                        "paraphrase_index": para_index,
                        "score": round(seed_score, 6),
                        "reason": "below_seed_threshold",
                        "question": paraphrase,
                    }
                )
            for other_index, other_vector in enumerate(base_vectors):
                if other_index == seed_index:
                    continue
                score = cosine_similarity(other_vector, vector)
                cross_group_scores.append(score)
                if score >= cfg.semantic_min_similarity:
                    failed_similarity.append(
                        {
                            "group_id": group.group_id,
                            "paraphrase_index": para_index,
                            "score": round(score, 6),
                            "reason": "too_close_to_other_seed",
                            "other_seed_index": other_index,
                            "question": paraphrase,
                        }
                    )
    if failed_similarity:
        raise ValueError(
            f"{qset.creator_id}: {len(failed_similarity)} runtime semantic similarity validations failed"
        )
    return {
        "base_pair_similarity_max": round(max(base_pair_scores), 6) if base_pair_scores else 0.0,
        "semantic_similarity_min": round(min(group_scores), 6) if group_scores else 0.0,
        "semantic_similarity_max": round(max(group_scores), 6) if group_scores else 0.0,
        "cross_group_similarity_max": round(max(cross_group_scores), 6) if cross_group_scores else 0.0,
        "failed_similarity_validations": failed_similarity,
        "all_texts": all_texts,
    }


def generate_runtime_semantic_group(
    creator: PreparedCreator,
    cfg: PrewarmConfig,
    seed_question: str,
    group_id: str,
    llm: LlmClient,
    fallback_llm: LlmClient | None,
    embedder: Embedder,
    avoid_questions: list[str],
    other_seed_questions: list[str],
    call_log: list[dict[str, Any]],
) -> tuple[RuntimeSemanticGroup, int, int, int]:
    context = creator_context(creator)
    target = cfg.runtime_paraphrases_per_seed
    attempts: list[tuple[str, LlmClient]] = [("nova_lite", llm)]
    for retry_index in range(cfg.runtime_nova_retry_attempts):
        attempts.append((f"nova_lite_retry_{retry_index + 1}", llm))
    if fallback_llm is not None:
        attempts.append(("haiku_fallback", fallback_llm))

    candidates: list[str] = []
    seen = {normalize_question(seed_question), *(normalize_question(q) for q in avoid_questions)}
    seed_vector = embedder.embed_batch([seed_question])[0]
    other_seed_vectors = embedder.embed_batch(other_seed_questions) if other_seed_questions else []
    nova_retries = 0
    haiku_fallbacks = 0
    failed_validations = 0

    for attempt_name, model in attempts:
        if attempt_name.startswith("nova_lite_retry"):
            nova_retries += 1
        if attempt_name == "haiku_fallback":
            haiku_fallbacks += 1
        prompt = build_runtime_paraphrase_prompt(
            profile=creator.profile,
            context=context,
            seed_question=seed_question,
            count=target,
            avoid_questions=avoid_questions + candidates,
        )
        t0 = time.perf_counter()
        raw = model.generate_json(prompt, max_tokens=max(3000, target * 160))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        generated = coerce_string_list(raw, "paraphrases")
        for paraphrase in generated:
            key = normalize_question(paraphrase)
            if key not in seen:
                seen.add(key)
                candidates.append(paraphrase)
        selected = select_runtime_paraphrases(
            seed_question=seed_question,
            seed_vector=seed_vector,
            other_seed_vectors=other_seed_vectors,
            candidates=candidates,
            embedder=embedder,
            target=target,
            threshold=cfg.semantic_min_similarity,
        )
        failed_validations += max(len(generated) - len(selected), 0)
        call_log.append(
            {
                "creator_id": creator.tenant_id,
                "runtime_semantic_group": group_id,
                "paraphrase_generation_attempt": attempt_name,
                "paraphrases_requested": target,
                "paraphrases_generated": len(generated),
                "paraphrases_candidates": len(candidates),
                "paraphrases_selected": len(selected),
                "elapsed_ms": round(elapsed_ms, 2),
            }
        )
        if len(selected) == target:
            return RuntimeSemanticGroup(group_id=group_id, seed_question=seed_question, paraphrases=selected), nova_retries, haiku_fallbacks, failed_validations

    for variant in runtime_paraphrase_variants(seed_question):
        key = normalize_question(variant)
        if key not in seen:
            seen.add(key)
            candidates.append(variant)
    selected = select_runtime_paraphrases(
        seed_question=seed_question,
        seed_vector=seed_vector,
        other_seed_vectors=other_seed_vectors,
        candidates=candidates,
        embedder=embedder,
        target=target,
        threshold=cfg.semantic_min_similarity,
    )
    call_log.append(
        {
            "creator_id": creator.tenant_id,
            "runtime_semantic_group": group_id,
            "deterministic_paraphrase_repair_used": True,
            "paraphrases_candidates": len(candidates),
            "paraphrases_selected": len(selected),
        }
    )
    if len(selected) != target:
        raise ValueError(f"{creator.tenant_id}: could not build {target} valid paraphrases for {group_id}")
    return RuntimeSemanticGroup(group_id=group_id, seed_question=seed_question, paraphrases=selected), nova_retries, haiku_fallbacks, failed_validations


def select_runtime_paraphrases(
    *,
    seed_question: str,
    seed_vector: list[float],
    other_seed_vectors: list[list[float]],
    candidates: list[str],
    embedder: Embedder,
    target: int,
    threshold: float,
) -> list[str]:
    candidates = [
        candidate
        for candidate in candidates
        if normalize_question(candidate) != normalize_question(seed_question)
    ]
    if not candidates:
        return []
    vectors = embedder.embed_batch(candidates)
    scored = [
        (cosine_similarity(seed_vector, vector), candidate, vector)
        for candidate, vector in zip(candidates, vectors)
    ]
    selected: list[str] = []
    seen: set[str] = {normalize_question(seed_question)}
    for score, candidate, vector in sorted(scored, key=lambda item: item[0], reverse=True):
        key = normalize_question(candidate)
        cross_score = max((cosine_similarity(vector, other) for other in other_seed_vectors), default=0.0)
        if score >= threshold and cross_score < threshold and key not in seen:
            selected.append(candidate)
            seen.add(key)
        if len(selected) == target:
            break
    return selected


def generate_runtime_question_set(
    creator: PreparedCreator,
    cfg: PrewarmConfig,
    llm: LlmClient,
    fallback_llm: LlmClient | None,
    embedder: Embedder,
    call_log: list[dict[str, Any]],
) -> tuple[RuntimeQuestionSet, dict[str, Any]]:
    base_questions, base_fallbacks = generate_runtime_base_questions(
        creator,
        cfg,
        llm,
        fallback_llm,
        embedder,
        call_log,
    )
    exact_seed_question = base_questions[0]
    semantic_seed_questions = base_questions[1:1 + cfg.runtime_semantic_seed_count]
    unique_miss_questions = base_questions[1 + cfg.runtime_semantic_seed_count:]
    exact_duplicates = [exact_seed_question for _ in range(cfg.runtime_exact_duplicate_count)]

    groups: list[RuntimeSemanticGroup] = []
    nova_retries = 0
    haiku_fallbacks = base_fallbacks
    failed_similarity_validations = 0
    avoid_questions = list(base_questions)
    for index, seed_question in enumerate(semantic_seed_questions, start=1):
        group, group_retries, group_fallbacks, group_failed = generate_runtime_semantic_group(
            creator,
            cfg,
            seed_question,
            f"semantic-{index:02d}",
            llm,
            fallback_llm,
            embedder,
            avoid_questions,
            [question for question in base_questions if question != seed_question],
            call_log,
        )
        groups.append(group)
        avoid_questions.extend(group.paraphrases)
        nova_retries += group_retries
        haiku_fallbacks += group_fallbacks
        failed_similarity_validations += group_failed

    qset = RuntimeQuestionSet(
        creator_id=creator.tenant_id,
        base_questions=base_questions,
        exact_seed_question=exact_seed_question,
        exact_duplicates=exact_duplicates,
        semantic_groups=groups,
        unique_miss_questions=unique_miss_questions,
    )
    validation = validate_runtime_question_set(qset, cfg, embedder)
    validation.update(
        {
            "nova_retries": nova_retries,
            "haiku_fallbacks": haiku_fallbacks,
            "sonnet_fallbacks": 0,
            "opus_fallbacks": 0,
            "model_escalation_attempts": 0,
            "failed_similarity_validation_count": failed_similarity_validations,
            "moved_to_unique_questions": qset.moved_to_unique_questions,
        }
    )
    return qset, validation


def fallback_model_bucket(label: str, model: LlmClient) -> str:
    model_ids = getattr(model, "_model_ids", [])
    model_id = str(model_ids[0] if model_ids else label).lower()
    label_lower = label.lower()
    if "opus" in model_id or "opus" in label_lower:
        return "opus_fallbacks"
    if "sonnet" in model_id or "sonnet" in label_lower:
        return "sonnet_fallbacks"
    return "haiku_fallbacks"


def fallback_model_label(model_id: str) -> str:
    lowered = model_id.lower()
    if "opus" in lowered:
        return "opus_fallback"
    if "sonnet" in lowered:
        return "sonnet_fallback"
    if "haiku" in lowered:
        return "haiku_fallback"
    return f"fallback:{model_id}"


def is_retryable_aws_error(exc: Exception) -> bool:
    text = str(exc).lower()
    retryable_fragments = [
        "throttl",
        "too many requests",
        "rate exceeded",
        "service unavailable",
        "internal server",
        "timeout",
        "temporarily unavailable",
        "connection",
    ]
    return any(fragment in text for fragment in retryable_fragments)


def generate_runtime_question_set_with_model_escalation(
    creator: PreparedCreator,
    cfg: PrewarmConfig,
    llm: LlmClient,
    fallback_llms: list[tuple[str, LlmClient]],
    embedder: Embedder,
    call_log: list[dict[str, Any]],
) -> tuple[RuntimeQuestionSet, dict[str, Any]]:
    attempts: list[tuple[str, LlmClient, LlmClient | None]] = [("nova_lite", llm, fallback_llms[0][1] if fallback_llms else None)]
    for index, (label, model) in enumerate(fallback_llms):
        next_model = fallback_llms[index + 1][1] if index + 1 < len(fallback_llms) else None
        attempts.append((label, model, next_model))

    last_exc: Exception | None = None
    for attempt_number, (label, primary, fallback) in enumerate(attempts, start=1):
        try:
            qset, validation = generate_runtime_question_set(
                creator,
                cfg,
                primary,
                fallback,
                embedder,
                call_log,
            )
            validation["model_escalation_attempts"] = attempt_number - 1
            if attempt_number > 1:
                bucket = fallback_model_bucket(label, primary)
                validation[bucket] = int(validation.get(bucket, 0)) + 1
            call_log.append(
                {
                    "creator_id": creator.tenant_id,
                    "runtime_model_escalation_attempt": attempt_number,
                    "runtime_model_label": label,
                    "runtime_model_success": True,
                }
            )
            return qset, validation
        except Exception as exc:
            last_exc = exc
            call_log.append(
                {
                    "creator_id": creator.tenant_id,
                    "runtime_model_escalation_attempt": attempt_number,
                    "runtime_model_label": label,
                    "runtime_model_success": False,
                    "error": str(exc),
                }
            )
            if attempt_number < len(attempts):
                logger.warning(
                    "Runtime generation/validation failed for %s with %s; escalating model (%s)",
                    creator.tenant_id,
                    label,
                    exc,
                )
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{creator.tenant_id}: no runtime generation attempts configured")


def simulator_records(qset: CreatorQuestionSet, run_id: str, timestamp: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seq = 1

    def make_record(question: str, expected_route: str, question_type: str) -> dict[str, Any]:
        nonlocal seq
        message_id = f"msg-{run_id}-{qset.creator_id}-{seq:03d}"
        seq += 1
        record = {
            "message_id": message_id,
            "lead_id": qset.creator_id,
            "tenant_id": qset.creator_id,
            "user_id": f"user-{qset.creator_id}-{seq - 1:03d}",
            "question_text": question,
            "timestamp": timestamp,
            "correlation_id": f"{run_id}:{message_id}",
            "run_id": run_id,
            "expected_route": expected_route,
            "question_type": question_type,
        }
        IncomingMessage(**record)
        return record

    for pair in qset.semantic_pairs:
        records.append(make_record(pair.paraphrase, EXPECTED_SEMANTIC, "semantic_paraphrase"))
    for seed in qset.exact_seeds:
        records.append(make_record(seed.question, EXPECTED_EXACT, "exact_seed"))
    for question in qset.full_miss_questions:
        records.append(make_record(question.question, EXPECTED_FULL_MISS, "full_miss"))
    return records


def runtime_simulator_records(qset: RuntimeQuestionSet, run_id: str, timestamp: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seq = 1

    def make_record(
        question: str,
        expected_route: str,
        question_type: str,
        *,
        stage: str,
        group_id: str,
        depends_on_message_id: str = "",
    ) -> dict[str, Any]:
        nonlocal seq
        message_id = f"msg-{run_id}-{qset.creator_id}-{seq:03d}"
        seq += 1
        record = {
            "message_id": message_id,
            "lead_id": qset.creator_id,
            "tenant_id": qset.creator_id,
            "user_id": f"user-{qset.creator_id}-{seq - 1:03d}",
            "question_text": question,
            "timestamp": timestamp,
            "correlation_id": f"{run_id}:{message_id}",
            "run_id": run_id,
            "expected_route": expected_route,
            "question_type": question_type,
            "runtime_stage": stage,
            "runtime_group_id": group_id,
            "depends_on_message_id": depends_on_message_id,
            "cache_build_mode": "runtime",
        }
        IncomingMessage(**record)
        return record

    seed_message_by_question: dict[str, str] = {}
    exact_seed = make_record(
        qset.exact_seed_question,
        EXPECTED_FULL_MISS,
        "runtime_exact_seed",
        stage="00_seed_miss",
        group_id="exact-01",
    )
    records.append(exact_seed)
    seed_message_by_question[qset.exact_seed_question] = exact_seed["message_id"]

    semantic_seed_questions = [group.seed_question for group in qset.semantic_groups]
    for index, seed_question in enumerate(semantic_seed_questions, start=1):
        record = make_record(
            seed_question,
            EXPECTED_FULL_MISS,
            "runtime_semantic_seed",
            stage="00_seed_miss",
            group_id=f"semantic-{index:02d}",
        )
        records.append(record)
        seed_message_by_question[seed_question] = record["message_id"]

    for index, question in enumerate(qset.unique_miss_questions, start=1):
        record = make_record(
            question,
            EXPECTED_FULL_MISS,
            "runtime_unique_miss",
            stage="00_seed_miss",
            group_id=f"unique-{index:02d}",
        )
        records.append(record)
        seed_message_by_question[question] = record["message_id"]

    for duplicate in qset.exact_duplicates:
        records.append(
            make_record(
                duplicate,
                EXPECTED_EXACT,
                "runtime_exact_duplicate",
                stage="01_cache_hit",
                group_id="exact-01",
                depends_on_message_id=seed_message_by_question[qset.exact_seed_question],
            )
        )

    for group in qset.semantic_groups:
        seed_message_id = seed_message_by_question[group.seed_question]
        for paraphrase in group.paraphrases:
            records.append(
                make_record(
                    paraphrase,
                    EXPECTED_SEMANTIC,
                    "runtime_semantic_paraphrase",
                    stage="01_cache_hit",
                    group_id=group.group_id,
                    depends_on_message_id=seed_message_id,
                )
            )
    return records


def prewarm_creator(
    qset: CreatorQuestionSet,
    validation: dict[str, Any],
    writer: PrewarmWriter,
    *,
    dry_run: bool,
    skip_cache_writes: bool = False,
    run_id: str = "",
) -> dict[str, Any]:
    exact_entries = [
        {
            "tenant_id": qset.creator_id,
            "pk": f"{qset.creator_id}#{question_hash(normalize_question(seed.question))}",
            "question": seed.question,
            "answer": seed.answer,
        }
        for seed in qset.exact_seeds
    ]
    semantic_entries = [
        {
            "tenant_id": qset.creator_id,
            "key": f"{KEY_PREFIX}{qset.creator_id}:{question_hash(normalize_question(pair.base_question))}",
            "question": pair.base_question,
            "answer": pair.answer,
        }
        for pair in qset.semantic_pairs
    ]
    if dry_run or skip_cache_writes:
        return {
            "exact_cache_seeds": len(qset.exact_seeds),
            "semantic_cache_seeds": len(qset.semantic_pairs),
            "exact_cache_entries": exact_entries,
            "semantic_cache_entries": semantic_entries,
        }

    base_embeddings = validation["base_embeddings"]
    for seed in qset.exact_seeds:
        writer.seed_exact_cache(qset.creator_id, seed.question, seed.answer, run_id)
    for pair, embedding in zip(qset.semantic_pairs, base_embeddings):
        writer.seed_semantic_cache(qset.creator_id, pair.base_question, pair.answer, embedding, run_id)
    return {
        "exact_cache_seeds": len(qset.exact_seeds),
        "semantic_cache_seeds": len(qset.semantic_pairs),
        "exact_cache_entries": exact_entries,
        "semantic_cache_entries": semantic_entries,
    }


def upload_records(
    records: list[dict[str, Any]],
    writer: PrewarmWriter,
    *,
    s3_output_prefix: str,
    run_id: str,
    records_per_batch: int,
    dry_run: bool,
) -> list[str]:
    bucket, prefix = s3_prefix_parts(s3_output_prefix, run_id)
    keys: list[str] = []
    for index in range(0, len(records), records_per_batch):
        batch = records[index:index + records_per_batch]
        batch_no = index // records_per_batch
        key = f"{prefix}batch-{batch_no:05d}.jsonl"
        keys.append(f"s3://{bucket}/{key}")
        if not dry_run:
            writer.upload_jsonl(bucket, key, batch)
    return keys


def upload_creator_records(
    creator_id: str,
    records: list[dict[str, Any]],
    writer: PrewarmWriter,
    *,
    s3_output_prefix: str,
    run_id: str,
    dry_run: bool,
) -> str:
    bucket, prefix = s3_prefix_parts(s3_output_prefix, run_id)
    key = f"{prefix}creators/{creator_id}.jsonl"
    uri = f"s3://{bucket}/{key}"
    if not dry_run:
        writer.upload_jsonl(bucket, key, records)
    return uri


def upload_runtime_creator_records(
    creator_id: str,
    records: list[dict[str, Any]],
    writer: PrewarmWriter,
    *,
    s3_output_prefix: str,
    run_id: str,
    dry_run: bool,
) -> list[dict[str, Any]]:
    bucket, prefix = s3_prefix_parts(s3_output_prefix, run_id)
    stage_specs = [
        ("00_seed_miss", "runtime-stage-00-seeds"),
        ("01_cache_hit", "runtime-stage-01-cache-hits"),
    ]
    uploaded: list[dict[str, Any]] = []
    for stage, stage_prefix in stage_specs:
        stage_records = [record for record in records if record.get("runtime_stage") == stage]
        key = f"{prefix}{stage_prefix}/creators/{creator_id}.jsonl"
        uri = f"s3://{bucket}/{key}"
        if not dry_run:
            writer.upload_jsonl(bucket, key, stage_records)
        uploaded.append({"stage": stage, "uri": uri, "records": len(stage_records)})
    return uploaded


def runtime_stage_keys(s3_output_prefix: str, run_id: str, creator_id: str) -> tuple[str, str, str]:
    bucket, prefix = s3_prefix_parts(s3_output_prefix, run_id)
    return (
        bucket,
        f"{prefix}runtime-stage-00-seeds/creators/{creator_id}.jsonl",
        f"{prefix}runtime-stage-01-cache-hits/creators/{creator_id}.jsonl",
    )


def existing_runtime_s3_completed_creators(
    writer: PrewarmWriter,
    *,
    s3_output_prefix: str,
    run_id: str,
    cfg: PrewarmConfig,
    validate_files: bool = False,
    creator_ids: list[str] | None = None,
) -> set[str]:
    bucket, prefix = s3_prefix_parts(s3_output_prefix, run_id)
    seed_prefix = f"{prefix}runtime-stage-00-seeds/creators/"
    hit_prefix = f"{prefix}runtime-stage-01-cache-hits/creators/"
    seed_keys = writer.list_keys(bucket, seed_prefix)
    hit_keys = writer.list_keys(bucket, hit_prefix)
    seed_key_set = set(seed_keys)
    hit_key_set = set(hit_keys)
    seed_by_creator_all = creator_stage_key_map(seed_keys, seed_prefix)
    hit_by_creator_all = creator_stage_key_map(hit_keys, hit_prefix)
    both_files_all = set(seed_by_creator_all) & set(hit_by_creator_all)
    completed = set(both_files_all)
    in_scope_completed = set()
    if creator_ids is not None:
        for creator_id in creator_ids:
            _, seed_key, hit_key = runtime_stage_keys(s3_output_prefix, run_id, creator_id)
            if seed_key in seed_key_set and hit_key in hit_key_set:
                in_scope_completed.add(creator_id)
    logger.info(
        "s3_resume_scan run_id=%s seed_creators_found=%s hit_creators_found=%s creators_with_both_files=%s existing_s3_completed_creators_by_existence=%s in_scope_creators=%s in_scope_complete_by_existence=%s validate_existing_s3_files=%s",
        run_id,
        len(seed_by_creator_all),
        len(hit_by_creator_all),
        len(both_files_all),
        len(completed),
        len(creator_ids) if creator_ids is not None else "all",
        len(in_scope_completed) if creator_ids is not None else len(completed),
        validate_files,
    )
    if not validate_files:
        return completed

    valid_completed: set[str] = set()
    invalid: list[dict[str, str]] = []
    for creator_id in sorted(completed):
        _, seed_key, hit_key = runtime_stage_keys(s3_output_prefix, run_id, creator_id)
        seed_error = validate_existing_runtime_stage_file(
            writer,
            bucket=bucket,
            key=seed_key,
            creator_id=creator_id,
            expected_rows=cfg.runtime_base_question_count,
            expected_stage="00_seed_miss",
        )
        hit_error = validate_existing_runtime_stage_file(
            writer,
            bucket=bucket,
            key=hit_key,
            creator_id=creator_id,
            expected_rows=cfg.runtime_exact_duplicate_count
            + cfg.runtime_semantic_seed_count * cfg.runtime_paraphrases_per_seed,
            expected_stage="01_cache_hit",
        )
        if seed_error or hit_error:
            if seed_error:
                invalid.append({"creator_id": creator_id, "key": seed_key, "error": seed_error})
            if hit_error:
                invalid.append({"creator_id": creator_id, "key": hit_key, "error": hit_error})
            continue
        valid_completed.add(creator_id)
    logger.info(
        "s3_resume_validation run_id=%s creators_with_both_files=%s creators_passing_validation=%s creators_rejected_by_validation=%s validation_is_diagnostic_only=True",
        run_id,
        len(completed),
        len(valid_completed),
        len(completed - valid_completed),
    )
    for item in invalid[:25]:
        logger.warning(
            "existing_s3_file_invalid creator_id=%s key=%s error=%s",
            item["creator_id"],
            item["key"],
            item["error"],
        )
    if len(invalid) > 25:
        logger.warning("existing_s3_file_invalid additional_invalid_files=%s", len(invalid) - 25)
    return completed


def creator_ids_from_runtime_stage_keys(keys: list[str], stage_prefix: str) -> set[str]:
    return set(creator_stage_key_map(keys, stage_prefix))


def creator_stage_key_map(keys: list[str], stage_prefix: str) -> dict[str, str]:
    creator_ids: set[str] = set()
    mapping: dict[str, str] = {}
    for key in keys:
        if not key.startswith(stage_prefix) or not key.endswith(".jsonl"):
            continue
        name = key[len(stage_prefix):-len(".jsonl")]
        if "/" not in name and name:
            creator_ids.add(name)
            mapping[name] = key
    return mapping


def validate_existing_runtime_stage_file(
    writer: PrewarmWriter,
    *,
    bucket: str,
    key: str,
    creator_id: str,
    expected_rows: int,
    expected_stage: str,
) -> str:
    try:
        text = writer.read_text(bucket, key)
    except Exception as exc:
        return f"read failed: {exc}"
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != expected_rows:
        return f"expected {expected_rows} JSONL rows, found {len(lines)}"
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            return f"line {line_number} malformed JSON: {exc}"
        if not isinstance(record, dict):
            return f"line {line_number} is not a JSON object"
        missing = REQUIRED_SIMULATOR_FIELDS - set(record)
        if missing:
            return f"line {line_number} missing required fields {sorted(missing)}"
        try:
            IncomingMessage(**record)
        except Exception as exc:
            return f"line {line_number} unsupported simulator schema: {exc}"
        if record.get("lead_id") != creator_id or record.get("tenant_id") != creator_id:
            return f"line {line_number} creator mismatch"
        if record.get("runtime_stage") != expected_stage:
            return f"line {line_number} expected runtime_stage {expected_stage!r}, found {record.get('runtime_stage')!r}"
    return ""


def validate_simulator_records(records: list[dict[str, Any]], cfg: PrewarmConfig, creator_id: str) -> None:
    if len(records) != cfg.questions_per_creator:
        raise ValueError(f"{creator_id}: expected {cfg.questions_per_creator} simulator records")
    seen_message_ids: set[str] = set()
    seen_questions: set[str] = set()
    for record in records:
        missing = REQUIRED_SIMULATOR_FIELDS - set(record)
        if missing:
            raise ValueError(f"{creator_id}: simulator record missing fields {sorted(missing)}")
        IncomingMessage(**record)
        if record["message_id"] in seen_message_ids:
            raise ValueError(f"{creator_id}: duplicate message_id {record['message_id']}")
        seen_message_ids.add(record["message_id"])
        question_key = normalize_question(record["question_text"])
        if question_key in seen_questions:
            is_runtime_exact_duplicate = (
                record.get("cache_build_mode") == "runtime"
                and record.get("expected_route") == EXPECTED_EXACT
                and record.get("question_type") == "runtime_exact_duplicate"
            )
            if not is_runtime_exact_duplicate:
                raise ValueError(f"{creator_id}: duplicate simulator question {record['question_text']!r}")
        seen_questions.add(question_key)
    route_counts = count_by(records, "expected_route")
    expected_counts = {
        EXPECTED_SEMANTIC: cfg.semantic_seed_count,
        EXPECTED_EXACT: cfg.exact_seed_count,
        EXPECTED_FULL_MISS: cfg.full_miss_count,
    }
    if route_counts != expected_counts:
        raise ValueError(f"{creator_id}: expected route counts {route_counts} != {expected_counts}")


def discover_creator_files(args: argparse.Namespace) -> list[Path]:
    folders = discover_creator_folders(Path(args.creators_root), args.only_folder or "")
    files = iter_creator_files(folders, args.limit)
    if args.creator_id:
        wanted = args.creator_id
        files = [
            path
            for path in files
            if path.stem == wanted or resolve_tenant_id_for_path(path) == wanted
        ]
    if not files:
        raise FileNotFoundError("no creator JSON files matched the requested filters")
    return files


def resolve_tenant_id_for_path(path: Path) -> str:
    """Return the canonical creator/tenant_id for a creator JSON file.

    The canonical tenant_id is what gets written to S3 keys, DynamoDB items,
    and MemoryDB keys (it comes from ``CreatorProfile.creator.creator_id``
    after ``normalize_creator_id``). The on-disk file stem may differ — for
    example, ``creator_2_chainz.json`` contains ``creator_id`` =
    ``creator_2chainz01`` — so the dispatch / S3 resume logic must key on the
    canonical ID, not the file stem.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return path.stem
    creator = raw.get("creator", {}) if isinstance(raw, dict) else {}
    raw_id = str(creator.get("creator_id") or "")
    creator_name = str(creator.get("creator_name") or "")
    try:
        return normalize_creator_id(raw_id, creator_name, path)
    except Exception:
        return path.stem


def build_tenant_id_index(paths: list[Path]) -> dict[Path, str]:
    return {path: resolve_tenant_id_for_path(path) for path in paths}


def build_aws_session(args: argparse.Namespace) -> boto3.Session:
    session_kwargs: dict[str, str] = {"region_name": args.region}
    profile = args.aws_profile or args.profile
    if profile:
        session_kwargs["profile_name"] = profile
    return boto3.Session(**session_kwargs)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def creator_artifact_path(artifacts_dir: Path, creator_id: str) -> Path:
    return artifacts_dir / "creators" / f"{creator_id}.json"


def checkpoint_path(artifacts_dir: Path) -> Path:
    return artifacts_dir / "checkpoint.json"


def default_checkpoint(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "completed_creators": [],
        "failed_creators": [],
        "failure_details": {},
        "last_completed_creator": "",
        "total_completed": 0,
        "timestamp": utc_now_iso(),
    }


def read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_checkpoint(artifacts_dir: Path, run_id: str) -> dict[str, Any]:
    path = checkpoint_path(artifacts_dir)
    checkpoint = default_checkpoint(run_id)
    if path.exists():
        loaded = read_json_file(path)
        if loaded.get("run_id") and loaded["run_id"] != run_id:
            raise ValueError(f"checkpoint run_id {loaded['run_id']} does not match {run_id}")
        checkpoint.update(loaded)

    local_completed: list[str] = []
    creators_dir = artifacts_dir / "creators"
    for creator_file in sorted(creators_dir.glob("*.json")) if creators_dir.exists() else []:
        try:
            payload = read_json_file(creator_file)
        except Exception as exc:
            logger.warning("Ignoring unreadable creator artifact %s: %s", creator_file, exc)
            continue
        if payload.get("run_id") == run_id and payload.get("status") == "completed":
            local_completed.append(str(payload.get("creator_id") or creator_file.stem))

    checkpoint_completed = [
        creator_id
        for creator_id in checkpoint.get("completed_creators", [])
        if creator_artifact_path(artifacts_dir, creator_id).exists()
    ]
    completed = dedupe_preserve_order(checkpoint_completed + local_completed)
    failed = [
        creator_id
        for creator_id in dedupe_preserve_order(list(checkpoint.get("failed_creators", [])))
        if creator_id not in set(completed)
    ]
    failure_details = dict(checkpoint.get("failure_details", {}))
    for creator_id in list(failure_details):
        if creator_id not in failed:
            failure_details.pop(creator_id, None)
    checkpoint["completed_creators"] = completed
    checkpoint["failed_creators"] = failed
    checkpoint["failure_details"] = failure_details
    checkpoint["last_completed_creator"] = completed[-1] if completed else ""
    checkpoint["total_completed"] = len(completed)
    checkpoint["timestamp"] = utc_now_iso()
    return checkpoint


def write_checkpoint(artifacts_dir: Path, checkpoint: dict[str, Any]) -> None:
    checkpoint["completed_creators"] = dedupe_preserve_order(list(checkpoint.get("completed_creators", [])))
    completed_set = set(checkpoint["completed_creators"])
    checkpoint["failed_creators"] = [
        creator_id
        for creator_id in dedupe_preserve_order(list(checkpoint.get("failed_creators", [])))
        if creator_id not in completed_set
    ]
    checkpoint["last_completed_creator"] = checkpoint["completed_creators"][-1] if checkpoint["completed_creators"] else ""
    checkpoint["total_completed"] = len(checkpoint["completed_creators"])
    checkpoint["timestamp"] = utc_now_iso()
    write_json(checkpoint_path(artifacts_dir), checkpoint)


def mark_creator_completed(checkpoint: dict[str, Any], creator_id: str) -> None:
    completed = list(checkpoint.get("completed_creators", []))
    if creator_id not in completed:
        completed.append(creator_id)
    checkpoint["completed_creators"] = completed
    checkpoint["failed_creators"] = [
        item for item in checkpoint.get("failed_creators", []) if item != creator_id
    ]
    checkpoint.get("failure_details", {}).pop(creator_id, None)


def mark_creator_failed(checkpoint: dict[str, Any], creator_id: str, error: Exception) -> None:
    if creator_id in set(checkpoint.get("completed_creators", [])):
        return
    failed = list(checkpoint.get("failed_creators", []))
    if creator_id not in failed:
        failed.append(creator_id)
    checkpoint["failed_creators"] = failed
    checkpoint.setdefault("failure_details", {})[creator_id] = {
        "error": str(error),
        "error_type": type(error).__name__,
        "timestamp": utc_now_iso(),
    }


def question_set_payload(qset: CreatorQuestionSet) -> dict[str, Any]:
    return {
        "semantic_pairs": [asdict(pair) for pair in qset.semantic_pairs],
        "exact_questions": [asdict(seed) for seed in qset.exact_seeds],
        "full_miss_questions": [asdict(question) for question in qset.full_miss_questions],
    }


def token_usage_snapshot(llm: LlmClient) -> dict[str, Any]:
    usage = getattr(llm, "token_usage", {"unavailable": True})
    return json.loads(json.dumps(usage))


def token_usage_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    if before.get("unavailable") or after.get("unavailable"):
        return {"unavailable": True}
    keys = ["input_tokens", "output_tokens", "total_tokens"]
    return {
        key: int(after.get(key, 0)) - int(before.get(key, 0))
        for key in keys
    } | {"unavailable": False}


def sum_token_usage(usages: list[dict[str, Any]]) -> dict[str, Any]:
    if not usages or any(usage.get("unavailable") for usage in usages):
        return {"unavailable": True}
    keys = ["input_tokens", "output_tokens", "total_tokens"]
    return {key: sum(int(usage.get(key, 0)) for usage in usages) for key in keys} | {"unavailable": False}


def attach_generation_file_logger(artifacts_dir: Path) -> None:
    log_path = artifacts_dir / "generation.log"
    target = str(log_path.resolve())
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == target:
            return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    root_logger.addHandler(handler)


def runtime_cache_reset_entries(qset: RuntimeQuestionSet) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    exact_entries: list[dict[str, str]] = []
    semantic_entries: list[dict[str, str]] = []
    for question in qset.base_questions:
        q_hash = question_hash(normalize_question(question))
        exact_entries.append(
            {
                "tenant_id": qset.creator_id,
                "pk": f"{qset.creator_id}#{q_hash}",
                "question": question,
            }
        )
        semantic_entries.append(
            {
                "tenant_id": qset.creator_id,
                "key": f"{KEY_PREFIX}{qset.creator_id}:{q_hash}",
                "question": question,
            }
        )
    return exact_entries, semantic_entries


def process_creator_runtime(
    *,
    path: Path,
    cfg: PrewarmConfig,
    kb_id: str,
    kb_prefix: str,
    llm: LlmClient,
    fallback_llms: list[tuple[str, LlmClient]],
    embedder: Embedder,
    writer: PrewarmWriter,
    args: argparse.Namespace,
    run_id: str,
    artifacts_dir: Path,
    s3_complete_creators: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    creator = load_creator_file(path, kb_id=kb_id, kb_source_prefix=kb_prefix)
    creator_id = creator.tenant_id
    if (
        not bool(getattr(args, "force_overwrite", False))
        and creator_id in (s3_complete_creators or frozenset())
    ):
        raise RuntimeError(
            f"START guard violated: {creator_id} is already complete in S3 and must not be processed"
        )
    logger.info("START %s worker=%s", creator_id, worker_label())
    started = time.perf_counter()
    generation_calls: list[dict[str, Any]] = []
    token_before = token_usage_snapshot(llm)
    embedding_calls_before = getattr(embedder, "calls", None)

    qset, validation = generate_runtime_question_set_with_model_escalation(
        creator,
        cfg,
        llm,
        fallback_llms,
        embedder,
        generation_calls,
    )
    embedding_calls_after = getattr(embedder, "calls", None)
    if isinstance(embedding_calls_before, int) and isinstance(embedding_calls_after, int):
        sagemaker_embedding_calls = embedding_calls_after - embedding_calls_before
    else:
        sagemaker_embedding_calls = 1

    records = runtime_simulator_records(qset, run_id, cfg.timestamp)
    validate_simulator_records(records, cfg, creator_id)
    s3_uploads = upload_runtime_creator_records(
        creator_id,
        records,
        writer,
        s3_output_prefix=args.s3_output_prefix or cfg.s3_output_prefix,
        run_id=run_id,
        dry_run=args.dry_run,
    )
    exact_reset_entries, semantic_reset_entries = runtime_cache_reset_entries(qset)
    route_counts = count_by(records, "expected_route")
    creator_report = {
        "creator_id": creator_id,
        "source_file": str(path),
        "simulator_generation_strategy": cfg.simulator_generation_strategy,
        "cache_build_mode": cfg.cache_build_mode,
        "simulator_questions": len(records),
        "generated_question_texts": qset.total_generated_text_count,
        "expected_route_counts": route_counts,
        "expected_bedrock_misses": cfg.runtime_base_question_count,
        "expected_exact_hits": cfg.runtime_exact_duplicate_count,
        "expected_semantic_hits": cfg.runtime_semantic_seed_count * cfg.runtime_paraphrases_per_seed,
        "exact_cache_seeds": 0,
        "semantic_cache_seeds": 0,
        "runtime_base_questions": len(qset.base_questions),
        "runtime_unique_miss_questions": len(qset.unique_miss_questions),
        "base_pair_similarity_max": validation["base_pair_similarity_max"],
        "semantic_similarity_min": validation["semantic_similarity_min"],
        "semantic_similarity_max": validation["semantic_similarity_max"],
        "cross_group_similarity_max": validation["cross_group_similarity_max"],
        "nova_retries": validation["nova_retries"],
        "haiku_fallbacks": validation["haiku_fallbacks"],
        "sonnet_fallbacks": validation.get("sonnet_fallbacks", 0),
        "opus_fallbacks": validation.get("opus_fallbacks", 0),
        "model_escalation_attempts": validation.get("model_escalation_attempts", 0),
        "failed_similarity_validations": validation["failed_similarity_validation_count"],
        "moved_to_unique_questions": validation["moved_to_unique_questions"],
        "s3_uploads": s3_uploads,
        "s3_uri": s3_uploads[0]["uri"] if s3_uploads else "",
        "repair_used": bool(validation["nova_retries"] or validation["haiku_fallbacks"] or validation["failed_similarity_validation_count"]),
        "similarity_repair_used": bool(validation["failed_similarity_validation_count"]),
        "fallback_used": bool(
            validation["haiku_fallbacks"]
            or validation.get("sonnet_fallbacks", 0)
            or validation.get("opus_fallbacks", 0)
            or validation.get("model_escalation_attempts", 0)
        ),
    }
    token_after = token_usage_snapshot(llm)
    artifact = {
        "run_id": run_id,
        "creator_id": creator_id,
        "status": "completed",
        "created_at": utc_now_iso(),
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "dry_run": bool(args.dry_run),
        "source_file": str(path),
        "s3_uri": creator_report["s3_uri"],
        "s3_uris": [item["uri"] for item in s3_uploads],
        "s3_uploads": s3_uploads,
        "runtime_question_set": {
            "base_questions": qset.base_questions,
            "exact_seed_question": qset.exact_seed_question,
            "exact_duplicates": qset.exact_duplicates,
            "semantic_groups": [asdict(group) for group in qset.semantic_groups],
            "unique_miss_questions": qset.unique_miss_questions,
            "moved_to_unique_questions": qset.moved_to_unique_questions,
        },
        "records": records,
        "creator_report": creator_report,
        "generation_calls": generation_calls,
        "bedrock_generation_calls": sum(
            1
            for call in generation_calls
            if call.get("runtime_base_generation_attempt") or call.get("paraphrase_generation_attempt")
        ),
        "sagemaker_embedding_calls": sagemaker_embedding_calls,
        "token_usage": token_usage_delta(token_before, token_after),
        "exact_cache_entries": [],
        "semantic_cache_entries": [],
        "runtime_exact_cache_reset_entries": exact_reset_entries,
        "runtime_semantic_cache_reset_entries": semantic_reset_entries,
    }
    write_json(creator_artifact_path(artifacts_dir, creator_id), artifact)
    logger.info("SUCCESS %s worker=%s", creator_id, worker_label())
    return artifact


def process_creator(
    *,
    path: Path,
    cfg: PrewarmConfig,
    kb_id: str,
    kb_prefix: str,
    llm: LlmClient,
    fallback_llms: list[tuple[str, LlmClient]],
    embedder: Embedder,
    writer: PrewarmWriter,
    args: argparse.Namespace,
    run_id: str,
    artifacts_dir: Path,
    s3_complete_creators: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    s3_complete_set = frozenset(s3_complete_creators or set())
    force_overwrite = bool(getattr(args, "force_overwrite", False))
    stem_id = path.stem
    canonical_id = resolve_tenant_id_for_path(path)
    if not force_overwrite and (stem_id in s3_complete_set or canonical_id in s3_complete_set):
        raise RuntimeError(
            f"START guard violated: {canonical_id} is already complete in S3 and must not be processed"
        )
    if cfg.simulator_generation_strategy == "runtime_cache_build":
        return process_creator_runtime(
            path=path,
            cfg=cfg,
            kb_id=kb_id,
            kb_prefix=kb_prefix,
            llm=llm,
            fallback_llms=fallback_llms,
            embedder=embedder,
            writer=writer,
            args=args,
            run_id=run_id,
            artifacts_dir=artifacts_dir,
            s3_complete_creators=s3_complete_set,
        )
    creator = load_creator_file(path, kb_id=kb_id, kb_source_prefix=kb_prefix)
    creator_id = creator.tenant_id
    if not force_overwrite and creator_id in s3_complete_set:
        raise RuntimeError(
            f"START guard violated: {creator_id} is already complete in S3 and must not be processed"
        )
    logger.info("START %s worker=%s", creator_id, worker_label())
    started = time.perf_counter()
    generation_calls: list[dict[str, Any]] = []
    token_before = token_usage_snapshot(llm)

    embedding_calls_before = getattr(embedder, "calls", None)
    fallback_used = False
    fallback_llm = fallback_llms[0][1] if fallback_llms else None
    try:
        qset = generate_creator_questions(creator, cfg, llm, generation_calls)
        validation = validate_embedding_similarity_with_repairs(creator, qset, cfg, embedder, generation_calls)
    except Exception as exc:
        if fallback_llm is None:
            raise
        logger.warning(
            "Primary generation/repair failed for %s after retries; falling back to %s: %s",
            creator_id,
            cfg.validation_fallback_model_id,
            exc,
        )
        fallback_used = True
        generation_calls.append(
            {
                "creator_id": creator_id,
                "fallback_model_id": cfg.validation_fallback_model_id,
                "fallback_reason": str(exc),
            }
        )
        qset = generate_creator_questions(creator, cfg, fallback_llm, generation_calls)
        validation = validate_embedding_similarity_with_repairs(creator, qset, cfg, embedder, generation_calls)

    embedding_calls_after = getattr(embedder, "calls", None)
    if isinstance(embedding_calls_before, int) and isinstance(embedding_calls_after, int):
        sagemaker_embedding_calls = embedding_calls_after - embedding_calls_before
    else:
        sagemaker_embedding_calls = 1

    seed_counts = prewarm_creator(
        qset,
        validation,
        writer,
        dry_run=args.dry_run,
        skip_cache_writes=args.skip_cache_writes,
        run_id=run_id,
    )
    records = simulator_records(qset, run_id, cfg.timestamp)
    validate_simulator_records(records, cfg, creator_id)
    s3_uri = upload_creator_records(
        creator_id,
        records,
        writer,
        s3_output_prefix=args.s3_output_prefix or cfg.s3_output_prefix,
        run_id=run_id,
        dry_run=args.dry_run,
    )

    route_counts = count_by(records, "expected_route")
    creator_report = {
        "creator_id": creator_id,
        "source_file": str(path),
        "simulator_questions": len(records),
        "generated_question_texts": qset.total_generated_text_count,
        "expected_route_counts": route_counts,
        "exact_cache_seeds": seed_counts["exact_cache_seeds"],
        "semantic_cache_seeds": seed_counts["semantic_cache_seeds"],
        "semantic_similarity_min": round(min(validation["semantic_pair_scores"]), 6),
        "semantic_similarity_max": round(max(validation["semantic_pair_scores"]), 6),
        "full_miss_max_seed_similarity": round(max(validation["full_miss_max_seed_scores"]), 6),
        "s3_uri": s3_uri,
        "repair_used": any(
            call.get("repair_used")
            or call.get("repair_attempt")
            or call.get("deterministic_count_repair_used")
            or call.get("full_miss_repaired_for_similarity")
            or call.get("semantic_similarity_repair_attempt")
            for call in generation_calls
        ),
        "similarity_repair_used": any(call.get("semantic_similarity_repair_attempt") for call in generation_calls),
        "fallback_used": fallback_used,
    }
    token_after = token_usage_snapshot(llm)
    artifact = {
        "run_id": run_id,
        "creator_id": creator_id,
        "status": "completed",
        "created_at": utc_now_iso(),
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "dry_run": bool(args.dry_run),
        "source_file": str(path),
        "s3_uri": s3_uri,
        "question_set": question_set_payload(qset),
        "records": records,
        "creator_report": creator_report,
        "generation_calls": generation_calls,
        "bedrock_generation_calls": sum(1 for call in generation_calls if "semantic_pairs_requested" in call),
        "sagemaker_embedding_calls": sagemaker_embedding_calls,
        "token_usage": token_usage_delta(token_before, token_after),
        "exact_cache_entries": seed_counts["exact_cache_entries"],
        "semantic_cache_entries": seed_counts["semantic_cache_entries"],
    }
    write_json(creator_artifact_path(artifacts_dir, creator_id), artifact)
    logger.info("SUCCESS %s worker=%s", creator_id, worker_label())
    return artifact


def process_creator_with_retry(
    *,
    path: Path,
    cfg: PrewarmConfig,
    kb_id: str,
    kb_prefix: str,
    llm: LlmClient,
    fallback_llms: list[tuple[str, LlmClient]],
    embedder: Embedder,
    writer: PrewarmWriter,
    args: argparse.Namespace,
    run_id: str,
    artifacts_dir: Path,
    force_overwrite: bool,
    s3_complete_creators: set[str] | frozenset[str] | None = None,
    checkpoint_complete_creators: set[str] | frozenset[str] | None = None,
    creator_id: str | None = None,
) -> dict[str, Any]:
    canonical_id = creator_id or resolve_tenant_id_for_path(path)
    stem_id = path.stem
    s3_complete_creators = frozenset(s3_complete_creators or set())
    checkpoint_complete_creators = frozenset(checkpoint_complete_creators or set())
    if not force_overwrite and (
        canonical_id in s3_complete_creators or stem_id in s3_complete_creators
    ):
        logger.info("SKIP %s (already complete in S3) worker=%s", canonical_id, worker_label())
        return {"status": "s3_completed", "creator_id": canonical_id, "skip_reason": "already_complete_in_s3"}
    if not force_overwrite and (
        canonical_id in checkpoint_complete_creators or stem_id in checkpoint_complete_creators
    ):
        logger.info("SKIP %s (already complete in checkpoint) worker=%s", canonical_id, worker_label())
        return {"status": "checkpoint_completed", "creator_id": canonical_id, "skip_reason": "already_complete_in_checkpoint"}
    creator_attempt = 0
    while True:
        creator_attempt += 1
        try:
            artifact = process_creator(
                path=path,
                cfg=cfg,
                kb_id=kb_id,
                kb_prefix=kb_prefix,
                llm=llm,
                fallback_llms=fallback_llms,
                embedder=embedder,
                writer=writer,
                args=args,
                run_id=run_id,
                artifacts_dir=artifacts_dir,
                s3_complete_creators=s3_complete_creators,
            )
            return {"status": "completed", "creator_id": str(artifact["creator_id"]), "artifact": artifact}
        except Exception as exc:
            if cfg.simulator_generation_strategy == "runtime_cache_build":
                try:
                    creator_s3_completed = existing_runtime_s3_completed_creators(
                        writer,
                        s3_output_prefix=args.s3_output_prefix or cfg.s3_output_prefix,
                        run_id=run_id,
                        cfg=cfg,
                        validate_files=bool(getattr(args, "validate_existing_s3_files", False)),
                        creator_ids=[canonical_id],
                    )
                except Exception:
                    creator_s3_completed = set()
                if canonical_id in creator_s3_completed and not force_overwrite:
                    logger.info(
                        "SKIP %s completed in S3 after exception worker=%s error=%s",
                        canonical_id,
                        worker_label(),
                        exc,
                    )
                    return {"status": "s3_completed", "creator_id": canonical_id, "error": str(exc)}
                if cfg.runtime_retry_until_success:
                    logger.warning(
                        "RETRY %s runtime attempt %s failed worker=%s (%s); retrying until success",
                        canonical_id,
                        creator_attempt,
                        worker_label(),
                        exc,
                        exc_info=True,
                    )
                    sleep_seconds = min(cfg.runtime_retry_sleep_seconds * max(creator_attempt, 1), 30.0)
                    if sleep_seconds:
                        time.sleep(sleep_seconds)
                    continue
            logger.error("FAILURE %s worker=%s (%s)", canonical_id, worker_label(), exc, exc_info=True)
            return {"status": "failed", "creator_id": canonical_id, "error": exc}


def completed_creator_artifacts(artifacts_dir: Path, checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for creator_id in checkpoint.get("completed_creators", []):
        path = creator_artifact_path(artifacts_dir, creator_id)
        if not path.exists():
            logger.warning("Completed creator %s is missing local artifact %s", creator_id, path)
            continue
        payload = read_json_file(path)
        if payload.get("status") == "completed":
            artifacts.append(payload)
    return artifacts


def rebuild_run_report(
    *,
    run_id: str,
    cfg: PrewarmConfig,
    artifacts_dir: Path,
    checkpoint: dict[str, Any],
    dry_run: bool,
    output_report: Path,
    started: float,
) -> dict[str, Any]:
    artifacts = completed_creator_artifacts(artifacts_dir, checkpoint)
    all_records: list[dict[str, Any]] = []
    creator_reports: list[dict[str, Any]] = []
    generation_calls: list[dict[str, Any]] = []
    exact_cache_entries: list[dict[str, str]] = []
    semantic_cache_entries: list[dict[str, str]] = []
    runtime_exact_cache_reset_entries: list[dict[str, str]] = []
    runtime_semantic_cache_reset_entries: list[dict[str, str]] = []
    s3_output: list[str] = []
    token_usages: list[dict[str, Any]] = []
    for artifact in artifacts:
        records = list(artifact.get("records", []))
        all_records.extend(records)
        creator_reports.append(dict(artifact.get("creator_report", {})))
        generation_calls.extend(list(artifact.get("generation_calls", [])))
        exact_cache_entries.extend(list(artifact.get("exact_cache_entries", [])))
        semantic_cache_entries.extend(list(artifact.get("semantic_cache_entries", [])))
        runtime_exact_cache_reset_entries.extend(list(artifact.get("runtime_exact_cache_reset_entries", [])))
        runtime_semantic_cache_reset_entries.extend(list(artifact.get("runtime_semantic_cache_reset_entries", [])))
        if artifact.get("s3_uris"):
            s3_output.extend(str(uri) for uri in artifact["s3_uris"])
        elif artifact.get("s3_uri"):
            s3_output.append(str(artifact["s3_uri"]))
        token_usages.append(dict(artifact.get("token_usage", {"unavailable": True})))

    expected_route_counts = count_by(all_records, "expected_route")
    stats = {
        "creators_processed": len(artifacts),
        "total_generated_questions": sum(int(item.get("generated_question_texts", 0)) for item in creator_reports),
        "total_s3_simulator_questions": len(all_records),
        "exact_cache_seeds": len(exact_cache_entries),
        "semantic_cache_seeds": len(semantic_cache_entries),
        "full_miss_questions": expected_route_counts.get(EXPECTED_FULL_MISS, 0),
        "expected_bedrock_misses": expected_route_counts.get(EXPECTED_FULL_MISS, 0),
        "expected_exact_hits": expected_route_counts.get(EXPECTED_EXACT, 0),
        "expected_semantic_hits": expected_route_counts.get(EXPECTED_SEMANTIC, 0),
        "bedrock_generation_calls": sum(1 for call in generation_calls if "semantic_pairs_requested" in call),
        "runtime_bedrock_generation_calls": sum(
            1
            for call in generation_calls
            if call.get("runtime_base_generation_attempt") or call.get("paraphrase_generation_attempt")
        ),
        "sagemaker_embedding_calls": sum(int(artifact.get("sagemaker_embedding_calls", 0)) for artifact in artifacts),
        "nova_retries": sum(int(item.get("nova_retries", 0)) for item in creator_reports),
        "haiku_fallbacks": sum(int(item.get("haiku_fallbacks", 0)) for item in creator_reports),
        "sonnet_fallbacks": sum(int(item.get("sonnet_fallbacks", 0)) for item in creator_reports),
        "opus_fallbacks": sum(int(item.get("opus_fallbacks", 0)) for item in creator_reports),
        "model_escalation_attempts": sum(int(item.get("model_escalation_attempts", 0)) for item in creator_reports),
        "failed_similarity_validations": sum(int(item.get("failed_similarity_validations", 0)) for item in creator_reports),
    }
    upload_manifest = {
        "run_id": run_id,
        "dry_run": bool(dry_run),
        "s3_output": [
            {
                "uri": artifact.get("s3_uri"),
                "uris": artifact.get("s3_uris", []),
                "stages": artifact.get("s3_uploads", []),
                "creator_id": artifact.get("creator_id"),
                "records": len(artifact.get("records", [])),
            }
            for artifact in artifacts
        ],
        "total_records": len(all_records),
    }
    cache_manifest = {
        "run_id": run_id,
        "dry_run": bool(dry_run),
        "exact_cache_entries": exact_cache_entries,
        "semantic_cache_entries": semantic_cache_entries,
        "runtime_exact_cache_reset_entries": runtime_exact_cache_reset_entries,
        "runtime_semantic_cache_reset_entries": runtime_semantic_cache_reset_entries,
        "counts": {
            "exact_cache_seeds": len(exact_cache_entries),
            "semantic_cache_seeds": len(semantic_cache_entries),
            "runtime_exact_cache_reset_entries": len(runtime_exact_cache_reset_entries),
            "runtime_semantic_cache_reset_entries": len(runtime_semantic_cache_reset_entries),
        },
    }
    generation_manifest = {
        "run_id": run_id,
        "dry_run": bool(dry_run),
        "generation_model_id": cfg.generation_model_id,
        "generation_fallback_model_ids": cfg.generation_fallback_model_ids,
        "validation_fallback_model_id": cfg.validation_fallback_model_id,
        "validation_fallback_model_ids": cfg.validation_fallback_model_ids,
        "max_creator_repair_attempts": cfg.max_creator_repair_attempts,
        "simulator_generation_strategy": cfg.simulator_generation_strategy,
        "cache_build_mode": cfg.cache_build_mode,
        "generation_batch_size": cfg.generation_batch_size,
        "bedrock_generation_calls": stats["bedrock_generation_calls"] + stats["runtime_bedrock_generation_calls"],
        "generation_calls": generation_calls,
        "creators": creator_reports,
        "token_usage": sum_token_usage(token_usages),
    }
    runtime_seconds = round(time.perf_counter() - started, 3)
    report = {
        "run_id": run_id,
        "dry_run": bool(dry_run),
        "created_at": utc_now_iso(),
        "runtime_seconds": runtime_seconds,
        "config": cfg.__dict__,
        "artifacts_dir": str(artifacts_dir),
        "checkpoint": checkpoint,
        "failures": checkpoint.get("failure_details", {}),
        "failed_creators": checkpoint.get("failed_creators", []),
        "s3_output": s3_output,
        "stats": stats,
        "expected_route_counts": expected_route_counts,
        "creators": creator_reports,
        "messages": all_records,
        "generation_manifest": generation_manifest,
        "cache_prewarm_manifest": cache_manifest,
        "uploaded_s3_input_manifest": upload_manifest,
        "run_level_statistics": {
            "total_creators": stats["creators_processed"],
            "total_generated_questions": stats["total_generated_questions"],
            "total_simulator_questions_uploaded": stats["total_s3_simulator_questions"],
            "expected_route_counts": expected_route_counts,
            "expected_bedrock_misses": stats["expected_bedrock_misses"],
            "expected_exact_hits": stats["expected_exact_hits"],
            "expected_semantic_hits": stats["expected_semantic_hits"],
            "bedrock_generation_calls": stats["bedrock_generation_calls"] + stats["runtime_bedrock_generation_calls"],
            "sagemaker_embedding_calls": stats["sagemaker_embedding_calls"],
            "nova_retries": stats["nova_retries"],
            "haiku_fallbacks": stats["haiku_fallbacks"],
            "sonnet_fallbacks": stats["sonnet_fallbacks"],
            "opus_fallbacks": stats["opus_fallbacks"],
            "model_escalation_attempts": stats["model_escalation_attempts"],
            "bedrock_llm_calls": "unavailable_until_pipeline_results",
            "kb_retrieval_calls": "unavailable_until_pipeline_results",
            "average_latency_per_stage": "unavailable_until_pipeline_results",
            "token_usage": generation_manifest["token_usage"],
            "total_runtime_seconds": runtime_seconds,
        },
    }
    write_json(artifacts_dir / "generation_manifest.json", generation_manifest)
    write_json(artifacts_dir / "cache_prewarm_manifest.json", cache_manifest)
    write_json(artifacts_dir / "uploaded_s3_input_manifest.json", upload_manifest)
    write_jsonl(artifacts_dir / "simulator_messages.jsonl", all_records)
    write_json(artifacts_dir / "final_summary_report.json", report)
    write_json(output_report, report)
    return report


def run_prewarm(
    args: argparse.Namespace,
    *,
    llm: LlmClient | None = None,
    embedder: Embedder | None = None,
    writer: PrewarmWriter | None = None,
) -> dict[str, Any]:
    cfg = load_prewarm_config(Path(args.config))
    kb_setup = load_kb_setup_config()
    kb_id = args.kb_id or kb_setup.get("BEDROCK_KB_ID") or runtime_config.BEDROCK_KB_ID or "shared_bedrock_kb"
    kb_prefix = args.kb_source_prefix or kb_setup.get("KB_SOURCE_PREFIX") or runtime_config.KB_SOURCE_PREFIX
    run_id = args.run_id or f"sim-prewarm-{int(time.time())}"
    started = time.perf_counter()
    artifacts_dir = run_artifact_dir(run_id, args.reports_root)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    attach_generation_file_logger(artifacts_dir)
    session = None if (llm and embedder and writer) else build_aws_session(args)
    if llm is None:
        llm = BedrockJsonClient(
            session=session,  # type: ignore[arg-type]
            model_id=cfg.generation_model_id,
            fallback_model_ids=cfg.generation_fallback_model_ids,
        )
    if embedder is None:
        embedder = SageMakerEmbedder(
            session=session,  # type: ignore[arg-type]
            endpoint_name=cfg.sagemaker_endpoint_name,
            batch_size=cfg.sagemaker_embedding_batch_size,
        )
    if writer is None:
        writer = (
            NoopPrewarmWriter()
            if args.dry_run
            else AwsPrewarmWriter(
                session=session,  # type: ignore[arg-type]
                exact_cache_table=args.exact_cache_table or cfg.exact_cache_table,
                memorydb_endpoint=args.memorydb_endpoint or runtime_config.MEMORYDB_ENDPOINT,
                memorydb_port=args.memorydb_port,
            )
        )
    validation_fallback_llms: list[tuple[str, LlmClient]] = []
    fallback_model_ids = dedupe_preserve_order(
        [cfg.validation_fallback_model_id, *list(cfg.validation_fallback_model_ids)]
    )
    if session is not None:
        for model_id in fallback_model_ids:
            if not model_id:
                continue
            validation_fallback_llms.append(
                (
                    fallback_model_label(model_id),
                    BedrockJsonClient(
                        session=session,
                        model_id=model_id,
                        fallback_model_ids=[],
                    ),
                )
            )

    creator_paths = discover_creator_files(args)
    tenant_id_by_path = build_tenant_id_index(creator_paths)
    all_creator_ids = set(tenant_id_by_path.values())
    stem_to_canonical: dict[str, str] = {
        path.stem: tenant_id_by_path[path]
        for path in creator_paths
        if path.stem != tenant_id_by_path[path]
    }
    checkpoint = load_checkpoint(artifacts_dir, run_id)
    write_checkpoint(artifacts_dir, checkpoint)
    force_overwrite = bool(getattr(args, "force_overwrite", False))

    # One-shot migration: pre-fix runs may have stored stems (path.stem) in
    # ``failed_creators`` and ``failure_details``. Convert any stem we can
    # resolve to its canonical creator_id so downstream s3_completed clearing
    # and dispatch logic match consistently.
    migrated_failed: list[tuple[str, str]] = []
    if stem_to_canonical:
        old_failed = list(checkpoint.get("failed_creators", []))
        new_failed: list[str] = []
        details = dict(checkpoint.get("failure_details", {}))
        for entry in old_failed:
            canonical = stem_to_canonical.get(entry)
            if canonical and canonical != entry:
                new_failed.append(canonical)
                if entry in details:
                    # Keep the detail under the canonical key; do not overwrite a
                    # newer canonical-keyed detail if one already exists.
                    if canonical not in details:
                        details[canonical] = details.pop(entry)
                    else:
                        details.pop(entry, None)
                migrated_failed.append((entry, canonical))
            else:
                new_failed.append(entry)
        checkpoint["failed_creators"] = dedupe_preserve_order(new_failed)
        checkpoint["failure_details"] = details
        if migrated_failed:
            logger.info(
                "checkpoint_failed_migrated_stem_to_canonical run_id=%s count=%s sample=%s",
                run_id,
                len(migrated_failed),
                ",".join(f"{stem}->{canon}" for stem, canon in migrated_failed[:5])
                + (" ..." if len(migrated_failed) > 5 else ""),
            )

    checkpoint_completed = set(checkpoint.get("completed_creators", []))
    completed = set() if force_overwrite else set(checkpoint_completed)
    failed = set(checkpoint.get("failed_creators", []))
    s3_completed: set[str] = set()
    if cfg.simulator_generation_strategy == "runtime_cache_build" and not force_overwrite:
        try:
            s3_completed = existing_runtime_s3_completed_creators(
                writer,
                s3_output_prefix=args.s3_output_prefix or cfg.s3_output_prefix,
                run_id=run_id,
                cfg=cfg,
                validate_files=bool(getattr(args, "validate_existing_s3_files", False)),
            )
        except Exception as exc:
            raise RuntimeError(f"Unable to scan S3 for completed runtime creators safely: {exc}") from exc

    def _matches_s3(creator_key: str) -> bool:
        if creator_key in s3_completed:
            return True
        canonical = stem_to_canonical.get(creator_key)
        return bool(canonical and canonical in s3_completed)

    cleared_failed: list[str] = []
    if s3_completed:
        cleared_failed = [
            creator_id
            for creator_id in checkpoint.get("failed_creators", [])
            if _matches_s3(creator_id)
        ]
        checkpoint["failed_creators"] = [
            creator_id
            for creator_id in checkpoint.get("failed_creators", [])
            if not _matches_s3(creator_id)
        ]
        for creator_id in cleared_failed:
            checkpoint.get("failure_details", {}).pop(creator_id, None)
        for creator_id in s3_completed:
            checkpoint.get("failure_details", {}).pop(creator_id, None)
        failed = set(checkpoint.get("failed_creators", []))
        if cleared_failed:
            logger.info(
                "checkpoint_failed_cleared run_id=%s count=%s reason=present_in_s3 ids=%s",
                run_id,
                len(cleared_failed),
                ",".join(sorted(cleared_failed)[:10])
                + (" ..." if len(cleared_failed) > 10 else ""),
            )
    checkpoint["s3_completed_creators"] = sorted(s3_completed)
    checkpoint["s3_completed_without_local_artifact"] = sorted(s3_completed - checkpoint_completed)
    write_checkpoint(artifacts_dir, checkpoint)
    existing_completed = completed | s3_completed
    failed_to_retry = failed - s3_completed
    skip_creators = existing_completed
    skipped_s3_complete: list[str] = []
    skipped_checkpoint_complete: list[str] = []
    if args.retry_failed:
        paths_to_process = []
        for path in creator_paths:
            cid = tenant_id_by_path[path]
            stem = path.stem
            in_retry = (
                cid in failed_to_retry
                or stem in failed_to_retry
                or (force_overwrite and (cid in failed or stem in failed))
            )
            if in_retry:
                paths_to_process.append(path)
        logger.info("Retrying %s failed creators for run %s", len(paths_to_process), run_id)
    else:
        paths_to_process = []
        for path in creator_paths:
            cid = tenant_id_by_path[path]
            stem = path.stem
            if force_overwrite:
                paths_to_process.append(path)
                continue
            if cid in s3_completed or stem in s3_completed:
                skipped_s3_complete.append(cid)
                continue
            if cid in checkpoint_completed or stem in checkpoint_completed:
                skipped_checkpoint_complete.append(cid)
                continue
            paths_to_process.append(path)
        if checkpoint.get("completed_creators"):
            logger.info(
                "Resuming run %s with %s completed creators already checkpointed",
                run_id,
                len(checkpoint["completed_creators"]),
            )

    failed_set = set(failed_to_retry if not force_overwrite else failed)
    failed_in_dispatch = sum(1 for path in paths_to_process if tenant_id_by_path[path] in failed_set)
    partial_to_reprocess = max(len(paths_to_process) - failed_in_dispatch, 0)

    logger.info(
        "checkpoint run_id=%s checkpoint_completed_creators=%s failed_creators=%s",
        run_id,
        len(checkpoint_completed),
        len(failed),
    )
    logger.info(
        "resume_state run_id=%s checkpoint_completed_creators=%s existing_s3_completed_creators=%s creators_to_process=%s force_overwrite=%s validate_existing_s3_files=%s",
        run_id,
        len(checkpoint_completed),
        len(s3_completed),
        len(paths_to_process),
        force_overwrite,
        bool(getattr(args, "validate_existing_s3_files", False)),
    )
    logger.info("failed_creators_to_retry=%s", len(failed_to_retry) if not force_overwrite else len(failed))

    leaked_completed = sorted(
        tenant_id_by_path[path]
        for path in paths_to_process
        if tenant_id_by_path[path] in skip_creators
    )
    if leaked_completed and not force_overwrite:
        raise RuntimeError(
            "Internal resume invariant failed: completed creators leaked into processing list: "
            + ", ".join(leaked_completed[:20])
        )

    processed_this_invocation = 0
    progress_every = max(int(getattr(args, "progress_every", 25) or 25), 1)
    max_workers = max(int(getattr(args, "max_workers", 5) or 5), 1)
    total_creators_in_scope = max(
        len(creator_paths),
        len(checkpoint.get("completed_creators", []))
        + len(paths_to_process)
        + len(checkpoint.get("failed_creators", [])),
    )
    logger.info(
        "dispatch run_id=%s creators_to_process=%s skipped_s3_complete=%s "
        "skipped_checkpoint_complete=%s partial_to_reprocess=%s failed_to_retry=%s "
        "max_workers=%s force_overwrite=%s",
        run_id,
        len(paths_to_process),
        len(skipped_s3_complete),
        len(skipped_checkpoint_complete),
        partial_to_reprocess,
        failed_in_dispatch,
        max_workers,
        force_overwrite,
    )
    logger.info(
        "dispatching creators_to_process=%s max_workers=%s worker_model=creator-level",
        len(paths_to_process),
        max_workers,
    )

    def update_s3_checkpoint_fields() -> None:
        checkpoint["s3_completed_creators"] = sorted(s3_completed)
        checkpoint["s3_completed_without_local_artifact"] = sorted(
            s3_completed - set(checkpoint.get("completed_creators", []))
        )

    canonical_to_stem = {tid: path.stem for path, tid in tenant_id_by_path.items()}

    def _aliases_for(creator_id: str) -> set[str]:
        aliases = {creator_id}
        canonical = stem_to_canonical.get(creator_id)
        if canonical:
            aliases.add(canonical)
        stem = canonical_to_stem.get(creator_id)
        if stem:
            aliases.add(stem)
        return aliases

    def _drop_aliases(items: list[str], aliases: set[str]) -> list[str]:
        return [item for item in items if item not in aliases]

    def apply_worker_result(result: dict[str, Any]) -> None:
        creator_id = str(result["creator_id"])
        aliases = _aliases_for(creator_id)
        status = result["status"]
        if status == "completed":
            mark_creator_completed(checkpoint, creator_id)
            checkpoint["failed_creators"] = _drop_aliases(
                checkpoint.get("failed_creators", []), aliases
            )
            for alias in aliases:
                checkpoint.get("failure_details", {}).pop(alias, None)
        elif status == "s3_completed":
            s3_completed.add(creator_id)
            skip_creators.add(creator_id)
            checkpoint["failed_creators"] = _drop_aliases(
                checkpoint.get("failed_creators", []), aliases
            )
            for alias in aliases:
                checkpoint.get("failure_details", {}).pop(alias, None)
        elif status == "checkpoint_completed":
            skip_creators.add(creator_id)
            checkpoint["failed_creators"] = _drop_aliases(
                checkpoint.get("failed_creators", []), aliases
            )
            for alias in aliases:
                checkpoint.get("failure_details", {}).pop(alias, None)
        elif status == "failed":
            error = result.get("error")
            if isinstance(error, Exception):
                mark_creator_failed(checkpoint, creator_id, error)
            else:
                mark_creator_failed(checkpoint, creator_id, RuntimeError(str(error)))
        update_s3_checkpoint_fields()

    futures: dict[concurrent.futures.Future[dict[str, Any]], str] = {}
    s3_complete_snapshot = frozenset(s3_completed)
    checkpoint_complete_snapshot = frozenset(checkpoint_completed)
    submitted_creator_ids: set[str] = set()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="prewarm-worker",
    ) as executor:
        for path in paths_to_process:
            creator_id = tenant_id_by_path[path]
            if not force_overwrite and (
                creator_id in s3_complete_snapshot or path.stem in s3_complete_snapshot
            ):
                logger.info("SKIP %s already complete in S3", creator_id)
                continue
            if not force_overwrite and (
                creator_id in checkpoint_complete_snapshot
                or path.stem in checkpoint_complete_snapshot
            ):
                logger.info("SKIP %s already complete in checkpoint", creator_id)
                continue
            if creator_id in submitted_creator_ids:
                logger.warning(
                    "duplicate_dispatch_prevented creator_id=%s path=%s",
                    creator_id,
                    path,
                )
                continue
            submitted_creator_ids.add(creator_id)
            future = executor.submit(
                process_creator_with_retry,
                path=path,
                cfg=cfg,
                kb_id=kb_id,
                kb_prefix=kb_prefix,
                llm=llm,
                fallback_llms=validation_fallback_llms,
                embedder=embedder,
                writer=writer,
                args=args,
                run_id=run_id,
                artifacts_dir=artifacts_dir,
                force_overwrite=force_overwrite,
                s3_complete_creators=s3_complete_snapshot,
                checkpoint_complete_creators=checkpoint_complete_snapshot,
                creator_id=creator_id,
            )
            futures[future] = creator_id

        for future in concurrent.futures.as_completed(futures):
            creator_id = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.error("FAILURE %s worker_result_unhandled (%s)", creator_id, exc, exc_info=True)
                result = {"status": "failed", "creator_id": creator_id, "error": exc}
            apply_worker_result(result)
            processed_this_invocation += 1
            write_checkpoint(artifacts_dir, checkpoint)
            if processed_this_invocation % progress_every == 0:
                report = rebuild_run_report(
                    run_id=run_id,
                    cfg=cfg,
                    artifacts_dir=artifacts_dir,
                    checkpoint=checkpoint,
                    dry_run=args.dry_run,
                    output_report=Path(args.output_report),
                    started=started,
                )
                logger.info(
                    "progress: %s/%s creators completed (%s failed)",
                    checkpoint["total_completed"],
                    total_creators_in_scope,
                    len(checkpoint.get("failed_creators", [])),
                )

    report = rebuild_run_report(
        run_id=run_id,
        cfg=cfg,
        artifacts_dir=artifacts_dir,
        checkpoint=checkpoint,
        dry_run=args.dry_run,
        output_report=Path(args.output_report),
        started=started,
    )
    logger.info(
        "progress: %s/%s creators completed (%s failed)",
        checkpoint["total_completed"],
        total_creators_in_scope,
        len(checkpoint.get("failed_creators", [])),
    )
    return report


def count_by(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    replace_with_retry(tmp_path, path)


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )
    replace_with_retry(tmp_path, path)


def replace_with_retry(tmp_path: Path, path: Path, attempts: int = 5) -> None:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            tmp_path.replace(path)
            return
        except PermissionError as exc:
            last_exc = exc
            if attempt == attempts:
                break
            time.sleep(0.05 * attempt)
    if last_exc:
        raise last_exc


def run_artifact_dir(run_id: str, reports_root: str) -> Path:
    return Path(reports_root).resolve() / run_id


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate/prewarm tenant-scoped LinkMe simulator questions."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--creators-root", default=str(REPO_ROOT / "creators"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--creator-id", default="", help="Process one creator JSON stem, e.g. creator_assiazar01")
    parser.add_argument("--only-folder", default="")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Resume from reports/simulator-runs/<RUN_ID>/checkpoint.json.")
    parser.add_argument("--retry-failed", action="store_true", help="Only retry creators marked failed in the checkpoint.")
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Allow regenerating and overwriting existing creator JSONL files for this RUN_ID.",
    )
    parser.add_argument(
        "--validate-existing-s3-files",
        action="store_true",
        help="During runtime resume, verify existing S3 creator files have valid JSONL and expected row counts.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=5,
        help="Maximum parallel creator workers. Default: 5.",
    )
    parser.add_argument("--progress-every", type=int, default=25, help="Log progress every N processed creators.")
    parser.add_argument(
        "--skip-cache-writes",
        action="store_true",
        help="Generate/upload artifacts but leave exact and semantic cache seeding to a VPC-side seeder.",
    )
    parser.add_argument("--profile", default="", help="Alias for --aws-profile")
    parser.add_argument("--aws-profile", default="")
    parser.add_argument("--region", default=runtime_config.AWS_REGION)
    parser.add_argument("--kb-id", default="")
    parser.add_argument("--kb-source-prefix", default="")
    parser.add_argument("--s3-output-prefix", default="")
    parser.add_argument("--exact-cache-table", default="")
    parser.add_argument("--memorydb-endpoint", default="")
    parser.add_argument("--memorydb-port", type=int, default=runtime_config.MEMORYDB_PORT)
    parser.add_argument("--output-report", default=str(DEFAULT_REPORT))
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        report = run_prewarm(args)
    except Exception as exc:
        logger.error("Simulator question prewarm failed: %s", exc, exc_info=True)
        return 1

    logger.info(
        "Prewarm complete: run_id=%s dry_run=%s creators=%s simulator_questions=%s exact=%s semantic=%s full_miss=%s",
        report["run_id"],
        report["dry_run"],
        report["stats"]["creators_processed"],
        report["stats"]["total_s3_simulator_questions"],
        report["stats"]["exact_cache_seeds"],
        report["stats"]["semantic_cache_seeds"],
        report["stats"]["full_miss_questions"],
    )
    if report.get("failed_creators"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
