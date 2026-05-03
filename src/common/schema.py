"""Creator profile schema -- the canonical source of truth for all tenant behavior.

Every field maps to a concrete enforcement point in the processing pipeline:
- agent.main_goal -> system prompt opening
- agent.tone -> tone instruction block
- agent.response_rules -> hard constraints in prompt
- agent.out_of_scope_reply -> guardrail fallback
- knowledge_base.kb_id -> metadata filter for KB retrieval
- creator.creator_id -> mandatory filter for MemoryDB cache
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ToneParameters(BaseModel):
    formality: int = Field(ge=0, le=100, description="0=very casual, 100=very formal")
    message_length: int = Field(
        ge=0, le=100, description="0=very short, 100=very long"
    )
    emoji_usage: int = Field(ge=0, le=100, description="0=no emoji, 100=heavy emoji")
    energy_level: int = Field(
        ge=0, le=100, description="0=calm/reserved, 100=very energetic"
    )


class ToneConfig(BaseModel):
    preset: Literal["friendly", "professional", "playful", "casual", "formal", "custom"]
    parameters: ToneParameters | None = None

    def model_post_init(self, __context: object) -> None:
        if self.preset == "custom" and self.parameters is None:
            raise ValueError("parameters required when preset is 'custom'")


class KBDocument(BaseModel):
    doc_id: str
    name: str
    type: Literal["pdf", "url", "text", "docx", "image"]
    source: str | None = None

    def model_post_init(self, __context: object) -> None:
        if self.type == "url" and not self.source:
            raise ValueError("source URL required when type is 'url'")


class KnowledgeBaseConfig(BaseModel):
    kb_id: str
    documents: list[KBDocument] = Field(default_factory=list, max_length=50)


class StyleTraining(BaseModel):
    dm_history_provided: bool = False
    dm_history_file: str | None = None

    def model_post_init(self, __context: object) -> None:
        if self.dm_history_provided and not self.dm_history_file:
            raise ValueError("dm_history_file required when dm_history_provided is True")


class AgentConfig(BaseModel):
    main_goal: str = Field(min_length=10, max_length=1000)
    out_of_scope_reply: str = Field(min_length=10, max_length=500)
    tone: ToneConfig
    response_rules: list[str] = Field(default_factory=list, max_length=10)


class CreatorIdentity(BaseModel):
    creator_id: str = Field(pattern=r"^creator_[a-z0-9_]+$")
    creator_name: str = Field(min_length=1, max_length=200)


class CreatorProfile(BaseModel):
    creator: CreatorIdentity
    agent: AgentConfig
    knowledge_base: KnowledgeBaseConfig
    style_training: StyleTraining = StyleTraining()
    version: int = 1
    created_at: str
    updated_at: str
