"""Generate test message datasets for load testing."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone

QUESTION_TEMPLATES = [
    "What products are available?",
    "How much does the main product cost?",
    "Is there a sale coming up?",
    "What sizes are available?",
    "Can I get a discount?",
    "What colors do you have?",
    "When will new items drop?",
    "Is this product good for everyday use?",
    "What's the return policy?",
    "Do you ship internationally?",
    "What's the most popular item?",
    "Can you compare two products for me?",
    "What material is this made from?",
    "How do I place an order?",
    "Is there a warranty?",
    "What's your recommendation for a beginner?",
    "Do you have any limited editions?",
    "What's the difference between model A and model B?",
    "Can I customize my order?",
    "What are the care instructions?",
]


def generate_messages(num_leads: int, msgs_per_lead: int) -> list[dict]:
    messages = []
    now = datetime.now(timezone.utc).isoformat()

    for lead_idx in range(num_leads):
        lead_id = f"creator_{lead_idx:05d}"
        for msg_idx in range(msgs_per_lead):
            question = QUESTION_TEMPLATES[msg_idx % len(QUESTION_TEMPLATES)]
            if msg_idx >= len(QUESTION_TEMPLATES):
                question = f"{question} (variation {msg_idx})"
            messages.append({
                "message_id": str(uuid.uuid4()),
                "lead_id": lead_id,
                "user_id": f"user_{lead_idx}_{msg_idx}",
                "question_text": question,
                "timestamp": now,
            })

    return messages


if __name__ == "__main__":
    num_leads = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    msgs_per = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    msgs = generate_messages(num_leads, msgs_per)
    print(json.dumps(msgs, indent=2))
    print(f"\nGenerated {len(msgs)} messages ({num_leads} leads x {msgs_per} each)", file=sys.stderr)
