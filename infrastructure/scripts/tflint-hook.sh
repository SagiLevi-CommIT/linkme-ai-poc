#!/usr/bin/env bash

set -euo pipefail

TF_LINT_CONFIG_FILE="${1:-}"

if [[ -z "$TF_LINT_CONFIG_FILE" ]]; then
  echo "Usage: tflint-hook.sh <path-to-.tflint.hcl>" >&2
  exit 1
fi

# Install plugins
tflint --config "${TF_LINT_CONFIG_FILE}" --init

# Run analysis
tflint --config "${TF_LINT_CONFIG_FILE}" --color --minimum-failure-severity=notice
