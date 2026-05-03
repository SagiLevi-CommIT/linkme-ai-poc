"""Pre-warm the semantic cache with anticipated Q&A pairs for Scenario B testing."""

from __future__ import annotations

import json
import logging
import sys

from common.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

QA_TEMPLATES = [
    ("What products are available?", "We have a wide range of products in our collection. Check out the latest drops on the official site!"),
    ("How much does the main product cost?", "Pricing varies by model and colorway. Visit the official store for current pricing."),
    ("Is there a sale coming up?", "We can't confirm future sales, but follow the official channels for announcements!"),
    ("What sizes are available?", "Most items come in a full size run. Check the product page for specific availability."),
    ("Can I get a discount?", "We don't currently offer direct discounts, but keep an eye out for seasonal promotions."),
    ("What colors do you have?", "Multiple colorways are available depending on the model. Check the store for the full lineup."),
    ("When will new items drop?", "New releases are announced on social media. Follow for the latest updates!"),
    ("Is this product good for everyday use?", "Absolutely! Our products are designed for both performance and everyday comfort."),
    ("What's the return policy?", "Returns are handled through the official store. Check their policy page for details."),
    ("Do you ship internationally?", "International shipping depends on the retailer. The official site has shipping info."),
    ("What's the most popular item?", "The latest model is the most popular right now. It's been getting great reviews!"),
    ("Can you compare two products for me?", "Each product has unique features. The newer model has updated cushioning and a lighter build."),
    ("What material is this made from?", "Premium materials including engineered mesh and responsive foam cushioning."),
    ("How do I place an order?", "Visit the official store online or check authorized retailers near you."),
    ("Is there a warranty?", "Products come with the manufacturer's standard warranty. Check the product page for specifics."),
    ("What's your recommendation for a beginner?", "Start with the entry-level model -- it offers great comfort and versatility."),
    ("Do you have any limited editions?", "Limited editions drop periodically. Follow social media for exclusive release announcements."),
    ("What's the difference between model A and model B?", "Model B has improved cushioning, updated traction, and a more breathable upper."),
    ("Can I customize my order?", "Customization options are available on select models through the official platform."),
    ("What are the care instructions?", "Wipe with a damp cloth, air dry, and avoid machine washing to maintain quality."),
]


def generate_seed_data(num_leads: int) -> list[dict]:
    """Generate seed Q&A pairs for pre-warming the cache."""
    seed_items = []
    for lead_idx in range(num_leads):
        lead_id = f"creator_{lead_idx:05d}"
        for question, answer in QA_TEMPLATES:
            seed_items.append({
                "lead_id": lead_id,
                "question": question,
                "answer": answer,
            })
    return seed_items


if __name__ == "__main__":
    num_leads = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    items = generate_seed_data(num_leads)
    print(json.dumps(items, indent=2))
    print(f"\nGenerated {len(items)} cache seed entries for {num_leads} leads", file=sys.stderr)
