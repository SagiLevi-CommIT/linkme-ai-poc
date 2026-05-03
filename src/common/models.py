"""Pydantic models for messages, responses, and batch processing."""

from __future__ import annotations

from enum import Enum

from pydantic import AliasChoices, BaseModel, Field


class CacheTier(str, Enum):
    EXACT_HIT = "exact_hit"
    SEMANTIC_HIGH_HIT = "semantic_high_hit"
    SEMANTIC_BORDERLINE = "semantic_borderline"
    FULL_MISS = "full_miss"


class MissType(str, Enum):
    BORDERLINE = "borderline"
    FULL_MISS = "full_miss"


class IncomingMessage(BaseModel):
    message_id: str
    lead_id: str
    user_id: str
    question_text: str = Field(validation_alias=AliasChoices("question_text", "question", "text"))
    timestamp: str
    correlation_id: str = ""
    run_id: str = ""
    # Ingestion time for PoC lifecycle (ISO 8601). Set by messages-pusher if absent.
    received_at: str = ""
    # Creator / tenant id for reporting (defaults to lead_id when omitted in JSONL).
    creator_id: str = ""


class CacheResult(BaseModel):
    tier: CacheTier
    similarity_score: float = 0.0
    cached_question: str | None = None
    cached_answer: str | None = None


class BatchQueueItem(BaseModel):
    """Sent from Cache Processor to Batch FIFO Queue on cache miss."""

    message_id: str
    lead_id: str
    question_text: str
    embedding_vector: list[float]
    miss_type: MissType
    similarity_score: float
    correlation_id: str
    run_id: str = ""
    received_at: str = ""
    creator_id: str = ""
    cached_question: str | None = None
    cached_answer: str | None = None


class BatchQuestion(BaseModel):
    id: str
    text: str


class BatchAnswer(BaseModel):
    id: str
    answer: str = Field(min_length=1)


class BatchResponse(BaseModel):
    answers: list[BatchAnswer] = Field(min_length=1)


class ProcessedResponse(BaseModel):
    message_id: str
    lead_id: str
    answer: str
    source: str  # "exact_cache", "semantic_cache", "borderline_adapt", "llm_haiku", "llm_sonnet"
    model_used: str
    latency_ms: float
    cache_tier: CacheTier
    correlation_id: str
