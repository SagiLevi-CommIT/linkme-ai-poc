#!/usr/bin/env bash
# Tear down the SageMaker embedding endpoint to stop hourly billing while
# the POC is idle. The Model and EndpointConfig remain, so sm-endpoint-up.sh
# can recreate the endpoint in ~5 min without any TF changes.
#
# Usage: ./sm-endpoint-down.sh [endpoint-name]

set -euo pipefail

ENDPOINT_NAME="${1:-linkme-poc-embedding}"
REGION="${AWS_REGION:-us-west-2}"

echo "Endpoint: $ENDPOINT_NAME"
echo "Region:   $REGION"
echo

if ! aws sagemaker describe-endpoint --endpoint-name "$ENDPOINT_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "Endpoint does not exist. Nothing to do."
  exit 0
fi

STATUS=$(aws sagemaker describe-endpoint --endpoint-name "$ENDPOINT_NAME" --region "$REGION" --query EndpointStatus --output text)
echo "Current status: $STATUS"

# Only InService and Failed endpoints are directly deletable. For other
# states we either wait (Creating/Updating) or short-circuit (Deleting).
# Deregistering autoscaling before waiting avoids an in-flight scaling
# action racing with the delete.
case "$STATUS" in
  InService|Failed)
    ;;
  Creating|Updating|SystemUpdating|RollingBack)
    echo "Endpoint is $STATUS - waiting for stable state before delete..."
    aws sagemaker wait endpoint-in-service \
      --endpoint-name "$ENDPOINT_NAME" \
      --region "$REGION"
    ;;
  Deleting)
    echo "Endpoint is already Deleting - waiting for completion."
    aws sagemaker wait endpoint-deleted \
      --endpoint-name "$ENDPOINT_NAME" \
      --region "$REGION"
    echo "Endpoint deleted."
    exit 0
    ;;
  *)
    echo "ERROR: unexpected endpoint status '$STATUS'." >&2
    exit 1
    ;;
esac

# Deregister the scalable target first so autoscaling doesn't try to act on
# a vanishing endpoint (harmless but noisy in CW alarms).
aws application-autoscaling deregister-scalable-target \
  --service-namespace sagemaker \
  --resource-id "endpoint/${ENDPOINT_NAME}/variant/primary" \
  --scalable-dimension sagemaker:variant:DesiredInstanceCount \
  --region "$REGION" 2>/dev/null || true

echo "Deleting endpoint..."
aws sagemaker delete-endpoint \
  --endpoint-name "$ENDPOINT_NAME" \
  --region "$REGION"

echo "Waiting for deletion to complete (prevents race with a follow-on sm:up)..."
aws sagemaker wait endpoint-deleted \
  --endpoint-name "$ENDPOINT_NAME" \
  --region "$REGION"

echo "Endpoint deleted. Billing stopped when the delete request was accepted."
echo "Run sm-endpoint-up.sh to bring it back before the next test."
