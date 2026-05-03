#!/usr/bin/env bash
# Idempotently create and configure the Terraform remote state S3 bucket.
# Runs as a Terragrunt before_hook on every terraform init so the bucket
# exists before Terraform tries to connect to it. Terragrunt's runner pool
# does not trigger S3 bucket auto-creation, making this hook necessary.
#
# Usage: ensure-state-bucket.sh <bucket-name> <region>

set -euo pipefail

BUCKET="$1"
REGION="$2"

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  exit 0
fi

echo "[terragrunt] Creating state bucket: $BUCKET ($REGION)"

if [ "$REGION" = "us-east-1" ]; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
else
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION"
fi

aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'

aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "[terragrunt] State bucket $BUCKET created"
