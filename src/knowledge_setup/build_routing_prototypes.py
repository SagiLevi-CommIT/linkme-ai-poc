"""Build simple/medium/complex centroid vectors for embedding-based routing.

Run this after SageMaker endpoint is deployed:
    python -m knowledge_setup.build_routing_prototypes --output prototypes.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from common.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

SIMPLE_QUESTIONS = [
    "What products are available?",
    "How much does it cost?",
    "What sizes do you have?",
    "Do you ship internationally?",
    "What colors are there?",
    "Is there a sale?",
    "When do new items release?",
    "What's the return policy?",
    "Hi there!",
    "Thanks!",
]

MEDIUM_QUESTIONS = [
    "What's the difference between model A and model B?",
    "How does this compare to last year's version?",
    "Can you explain the technology used?",
    "What makes this product special?",
    "How long does shipping usually take?",
]

COMPLEX_QUESTIONS = [
    "Compare the LeBron 21 to the LeBron 20, considering cushioning, weight, traction, and price, and tell me which is better for outdoor basketball.",
    "I have flat feet and need a shoe for both running and casual wear. Which model would you recommend and why?",
    "Can you create a detailed comparison table of all available models with pros and cons for each?",
    "I'm buying gifts for three different people with different needs. What would you suggest for each?",
    "What's the long-term durability like and is it worth the premium price over alternatives?",
]


def compute_centroid(embeddings: list[list[float]]) -> list[float]:
    if not embeddings:
        return []
    dim = len(embeddings[0])
    centroid = [0.0] * dim
    for emb in embeddings:
        for i in range(dim):
            centroid[i] += emb[i]
    return [v / len(embeddings) for v in centroid]


def build_prototypes(embed_fn) -> dict[str, list[float]]:  # type: ignore[type-arg]
    """Build prototype centroids. `embed_fn` takes a list[str] and returns list[list[float]]."""
    logger.info("Embedding %d simple prototypes", len(SIMPLE_QUESTIONS))
    simple_embs = embed_fn(SIMPLE_QUESTIONS)

    logger.info("Embedding %d medium prototypes", len(MEDIUM_QUESTIONS))
    medium_embs = embed_fn(MEDIUM_QUESTIONS)

    logger.info("Embedding %d complex prototypes", len(COMPLEX_QUESTIONS))
    complex_embs = embed_fn(COMPLEX_QUESTIONS)

    return {
        "simple": compute_centroid(simple_embs),
        "medium": compute_centroid(medium_embs),
        "complex": compute_centroid(complex_embs),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="prototypes.json")
    args = parser.parse_args()

    from cache_processor.embedding_client import embed_batch

    prototypes = build_prototypes(lambda texts: embed_batch(texts))

    with open(args.output, "w") as f:
        json.dump(prototypes, f)
    print(f"Wrote prototypes to {args.output}", file=sys.stderr)
