"""Structured multi-question batch prompt for Bedrock LLM."""

from __future__ import annotations

import json

from common.models import BatchQuestion


def build_batch_prompt(system_prompt: str, questions: list[BatchQuestion]) -> str:
    """Build the full prompt for a batched LLM call.

    The LLM receives the shared system prompt + KB context once,
    then a JSON array of questions with IDs, and must return a JSON
    object with answers keyed by ID.
    """
    q_json = json.dumps(
        [{"id": q.id, "text": q.text} for q in questions], indent=2
    )

    return (
        f"{system_prompt}\n\n"
        "Below are multiple questions from different users. "
        "Answer each one independently.\n"
        "Do not merge answers. Do not cross-reference between questions.\n"
        "Each answer must match its question ID exactly.\n\n"
        f"QUESTIONS:\n{q_json}\n\n"
        'Return ONLY a valid JSON object in this exact format:\n'
        '{"answers": [{"id": "q1", "answer": "your answer"}, '
        '{"id": "q2", "answer": "your answer"}]}'
    )


def build_borderline_adaptation_prompt(
    system_prompt: str,
    cached_question: str,
    cached_answer: str,
    actual_question: str,
) -> str:
    """Lightweight adaptation prompt for borderline cache hits."""
    return (
        f"{system_prompt}\n\n"
        "A similar question was already answered. Adapt the existing answer "
        "to match the user's actual question.\n"
        "Only adjust phrasing. Do not add new information. Do not change facts.\n\n"
        f"Previously answered question: {cached_question}\n"
        f"Previous answer: {cached_answer}\n"
        f"User's actual question: {actual_question}\n\n"
        "Adapted answer:"
    )
