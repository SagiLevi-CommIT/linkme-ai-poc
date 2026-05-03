"""Generate N test creator profiles for load testing."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from common.schema import CreatorProfile

GOALS = [
    "Help fans learn about {name}'s product collection -- answer questions about styles, availability, and how to get them.",
    "Assist followers with questions about {name}'s content, schedule, and brand collaborations.",
    "Guide fans through {name}'s merch store -- help with sizing, pricing, and order status.",
]

TONES = ["friendly", "professional", "playful", "casual"]

RULES_POOL = [
    "Never mention competing brands.",
    "Do not discuss personal life or family.",
    "Never make promises about restock dates.",
    "Keep answers concise and under 3 sentences.",
    "Always suggest checking the official website for latest info.",
]


def generate_profiles(count: int) -> list[CreatorProfile]:
    profiles = []
    now = datetime.now(timezone.utc).isoformat()

    for i in range(count):
        name = f"Creator_{i:05d}"
        profile = CreatorProfile(
            creator={
                "creator_id": f"creator_{i:05d}",
                "creator_name": name,
            },
            agent={
                "main_goal": GOALS[i % len(GOALS)].format(name=name),
                "out_of_scope_reply": f"I'm only here to talk about {name}'s content. Check official channels for anything else.",
                "tone": {"preset": TONES[i % len(TONES)]},
                "response_rules": RULES_POOL[: (i % 3) + 1],
            },
            knowledge_base={"kb_id": f"kb_{i:05d}", "documents": []},
            created_at=now,
            updated_at=now,
        )
        profiles.append(profile)

    return profiles


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    profiles = generate_profiles(count)
    output = [p.model_dump() for p in profiles]
    print(json.dumps(output, indent=2))
    print(f"\nGenerated {len(profiles)} profiles", file=sys.stderr)
