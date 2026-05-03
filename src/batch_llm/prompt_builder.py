"""Schema-driven system prompt construction from CreatorProfile."""

from __future__ import annotations

from common.schema import CreatorProfile, ToneConfig

_TONE_PRESETS = {
    "friendly": "Be warm, approachable, and use a conversational tone.",
    "professional": "Maintain a polished, business-appropriate tone.",
    "playful": "Be fun, witty, and lighthearted.",
    "casual": "Keep it relaxed and informal, like texting a friend.",
    "formal": "Use proper grammar and a respectful, measured tone.",
}


def build_tone_block(tone: ToneConfig) -> str:
    if tone.preset != "custom":
        return _TONE_PRESETS.get(tone.preset, "")
    p = tone.parameters
    if not p:
        return ""
    return (
        f"Formality: {p.formality}/100. "
        f"Message length: {p.message_length}/100. "
        f"Emoji usage: {p.emoji_usage}/100. "
        f"Energy level: {p.energy_level}/100."
    )


def build_system_prompt(profile: CreatorProfile, kb_chunks: str = "") -> str:
    tone_block = build_tone_block(profile.agent.tone)
    rules = "\n".join(
        f"{i+1}. {rule}" for i, rule in enumerate(profile.agent.response_rules)
    )

    return (
        f"You are an AI assistant for {profile.creator.creator_name}.\n"
        f"Your goal: {profile.agent.main_goal}\n\n"
        f"TONE INSTRUCTIONS:\n{tone_block}\n\n"
        f"HARD RULES (you MUST follow these):\n{rules}\n\n"
        f'If the user asks about anything outside your goal, respond exactly with:\n'
        f'"{profile.agent.out_of_scope_reply}"\n\n'
        f"CONTEXT FROM KNOWLEDGE BASE:\n{kb_chunks}"
    )
