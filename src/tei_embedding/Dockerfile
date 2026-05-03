# Thin SageMaker-aware wrapper over HuggingFace Text Embeddings Inference (TEI).
#
# TEI's `text-embeddings-router` rejects SageMaker's `serve` positional arg;
# entrypoint.sh strips all positional args and invokes the router from env
# vars instead. Image is rebased on the upstream TEI container for the
# target GPU architecture:
#   - turing-1.6 : Turing / CC 7.5 (T4 - g4dn family)
#   - 86-1.6     : Ampere / CC 8.6 (A10G - g5 family)
# The tag used here is driven by the buildspec's TEI_BASE_TAG env.

ARG TEI_BASE_TAG=turing-1.6
FROM ghcr.io/huggingface/text-embeddings-inference:${TEI_BASE_TAG}

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
