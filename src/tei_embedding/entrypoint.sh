#!/bin/bash
# SageMaker inference containers receive `serve` as the first positional
# argument. TEI's text-embeddings-router rejects unknown positionals, so
# we ignore "$@" entirely and drive the router from env vars only.
set -e

exec text-embeddings-router \
  --model-id "${MODEL_ID:-BAAI/bge-base-en-v1.5}" \
  --hostname 0.0.0.0 \
  --port "${PORT:-8080}" \
  --max-batch-tokens "${MAX_BATCH_TOKENS:-65536}" \
  --max-concurrent-requests "${MAX_CONCURRENT_REQUESTS:-512}" \
  --max-client-batch-size "${MAX_CLIENT_BATCH_SIZE:-128}"
