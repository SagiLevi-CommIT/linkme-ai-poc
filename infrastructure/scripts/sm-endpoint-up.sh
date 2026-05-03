#!/usr/bin/env bash
# Bring the SageMaker embedding endpoint up from its existing EndpointConfig.
# Model and EndpointConfig are free — only the endpoint (running instances)
# is billed. Use sm-endpoint-down.sh to tear it down between tests.
#
# Usage: ./sm-endpoint-up.sh [endpoint-name] [endpoint-config-name]

set -euo pipefail

ENDPOINT_NAME="${1:-linkme-poc-embedding}"
CONFIG_NAME="${2:-linkme-poc-embedding-tei-g4dnx1}"
REGION="${AWS_REGION:-us-west-2}"

echo "Endpoint: $ENDPOINT_NAME"
echo "Config:   $CONFIG_NAME"
echo "Region:   $REGION"
echo

if aws sagemaker describe-endpoint --endpoint-name "$ENDPOINT_NAME" --region "$REGION" >/dev/null 2>&1; then
  STATUS=$(aws sagemaker describe-endpoint --endpoint-name "$ENDPOINT_NAME" --region "$REGION" --query EndpointStatus --output text)
  case "$STATUS" in
    InService)
      echo "Endpoint already InService. Nothing to do."
      exit 0
      ;;
    Creating|Updating|SystemUpdating|RollingBack)
      echo "Endpoint is $STATUS. Waiting for InService..."
      aws sagemaker wait endpoint-in-service --endpoint-name "$ENDPOINT_NAME" --region "$REGION"
      echo "Endpoint is InService."
      exit 0
      ;;
    Failed)
      echo "ERROR: endpoint is in Failed state. Delete it (task sm:down) and retry." >&2
      exit 1
      ;;
    Deleting)
      echo "Endpoint is Deleting. Waiting for teardown before recreating..."
      aws sagemaker wait endpoint-deleted --endpoint-name "$ENDPOINT_NAME" --region "$REGION"
      ;;
    *)
      echo "ERROR: unexpected endpoint status '$STATUS'." >&2
      exit 1
      ;;
  esac
fi

echo "Creating endpoint..."
aws sagemaker create-endpoint \
  --endpoint-name "$ENDPOINT_NAME" \
  --endpoint-config-name "$CONFIG_NAME" \
  --region "$REGION" \
  --query EndpointArn --output text

echo
echo "Waiting for InService (typically ~5 min for g4dn.xlarge + TEI)..."
aws sagemaker wait endpoint-in-service \
  --endpoint-name "$ENDPOINT_NAME" \
  --region "$REGION"

echo "Endpoint is InService."
