# LinkMe AI POC — Deployment Guide

## Prerequisites

```bash
# Tools required
terraform    >= 1.13.0
terragrunt   >= 0.90.0
aws-cli      >= 2.x  (with sso configured)
docker       (running, for CodeBuild ARM builds)
tflint       (optional but hooked into plan/apply)
git

# AWS SSO login (profile: commit-ai-sandbox-01)
aws sso login --profile commit-ai-sandbox-01

# Verify identity
AWS_PROFILE=commit-ai-sandbox-01 aws sts get-caller-identity
```

---

## Phase 0 — Bootstrap (one-time, manual)

**The Terraform state S3 bucket is created automatically by Terragrunt** on first `init`/`apply`
with versioning, AES256 encryption, and public-access-block already enabled. No manual S3 setup
is needed.

The only resources that must exist before Terragrunt can run are the **CodeCommit repository**
(stores the code) and a valid AWS SSO session.

```bash
# 1. Create CodeCommit repository
aws codecommit create-repository \
  --region us-west-2 \
  --repository-name linkme-ai-poc \
  --repository-description "LinkMe AI POC" \
  --profile commit-ai-sandbox-01

# 2. Push code to CodeCommit
git remote add origin \
  https://git-codecommit.us-west-2.amazonaws.com/v1/repos/linkme-ai-poc
git push -u origin main
```

> **How state bucket auto-creation works:** `terragrunt_base.hcl` has a `before_hook`
> that runs `ensure-state-bucket.sh` on every `init`. The script idempotently creates
> `terraform-states-<account_id>-<region>` with versioning, AES256 encryption, and
> public-access-block enabled.

---

## Phase 1 — All infrastructure layers

Terragrunt respects the DAG and applies units in the correct order automatically.
The `ai` layer runs in parallel with `app` since both depend only on `vpc`.
The `messaging` and `cicd` layers run after `app` (both depend on app + vpc).

```
vpc  (no deps)
 ├──► app       ──► cicd
 │     └──► messaging
 └──► ai
```

```bash
cd infrastructure/accounts/commit-ai-sandbox-01/us-west-2
terragrunt run --all apply
# Type: y  (Terragrunt run-all confirmation)
# Type: yes  (Terraform confirmation per unit)
```

**Resources created per layer (with current flags):**

| Layer | Key resources |
|-------|---------------|
| **vpc** | VPC, IGW, NAT Gateway, 6 subnets (2 AZs), route tables, VPC Flow Logs, VPC endpoints (S3, Bedrock, ECR, CloudWatch, SQS), default SG deny-all |
| **app** | KMS key, ECR repos (5), ECS cluster, backend SG + IAM role, CloudWatch logs. No ALB/frontend (`enable_frontend = false`). |
| **ai** | S3 KB data bucket + logs bucket, S3 Vectors bucket + index, Bedrock KB + S3 data source, Bedrock Agent (Sonnet 4.6) + alias + KB association, IAM roles (KB, Agent). No Lambda (`enable_preprocessor = false`). |
| **messaging** | SQS queues (AI + Publisher) + DLQs + alarms, MemoryDB cluster + subnet group + ACL. No ECS services (`enable_phase2_services = false`). No auto-scaling (`enable_autoscaling = false`). |
| **cicd** | S3 artifacts + access-logs buckets, CodeBuild backend project + role |

**Optional — set ECR push policies after first deploy:**

Once the CodeBuild role ARN is known, restrict ECR push to only that role:

```hcl
# infrastructure/accounts/commit-ai-sandbox-01/us-west-2/region.hcl
ecr_push_role_arns = {
  backend = "<backend_codebuild_role_arn>"
}
```

Then re-apply: `cd app && terragrunt apply`

---

## Phase 2 — Backend Pipeline

The backend pipeline builds the AgentCore runtime container and deploys it.

```bash
# Trigger
aws codebuild start-build \
  --region us-west-2 \
  --project-name linkme-ai-poc-backend-build \
  --profile commit-ai-sandbox-01

# Monitor (~12 min: 2 min build + up to 10 min AgentCore READY wait)
BUILD_ID="linkme-ai-poc-backend-build:<id>"
watch -n 30 "AWS_PROFILE=commit-ai-sandbox-01 aws codebuild batch-get-builds \
  --region us-west-2 --ids $BUILD_ID \
  --query 'builds[0].{Status:buildStatus,Phase:currentPhase}' --output table"
```

**Buildspec steps:**

1. `docker login` to ECR
2. `docker build --platform linux/arm64` — builds Python agent with bundled model
3. `docker push` → ECR `linkme-ai-poc-backend:<commit-hash-timestamp>`
4. `aws bedrock-agentcore-control create-agent-runtime` with:
   - Container URI from ECR
   - Execution role: `role-linkme-ai-poc-agentcore`
   - VPC config: private-app subnets + AgentCore security group
   - Env vars: `BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-6`, `AWS_DEFAULT_REGION`
5. Polls runtime status every 30s until `READY`
6. Writes `AGENTCORE_RUNTIME_ARN` to `agentcore_runtime.env` artifact

**Verify:**

```bash
AWS_PROFILE=commit-ai-sandbox-01 \
aws bedrock-agentcore-control list-agent-runtimes \
  --region us-west-2 \
  --query 'agentRuntimes[*].{Name:agentRuntimeName,Status:status}' \
  --output table
# Expected: Status = READY
```

---

## Phase 3 — E2E Verification

```bash
# 1. Direct backend invocation via AgentCore
RUNTIME_ARN=$(AWS_PROFILE=commit-ai-sandbox-01 \
  aws bedrock-agentcore-control list-agent-runtimes \
  --region us-west-2 \
  --query 'agentRuntimes[0].agentRuntimeArn' --output text)

PAYLOAD=$(echo -n '{"prompt": "Test prompt for LinkMe AI"}' | base64)

AWS_PROFILE=commit-ai-sandbox-01 \
aws bedrock-agentcore invoke-agent-runtime \
  --region us-west-2 \
  --agent-runtime-arn "$RUNTIME_ARN" \
  --payload "$PAYLOAD" \
  --qualifier DEFAULT \
  /tmp/response.json

cat /tmp/response.json | python3 -m json.tool

# 2. Bedrock Agent invocation
AGENT_ID=$(AWS_PROFILE=commit-ai-sandbox-01 \
  aws bedrock-agent list-agents \
  --region us-west-2 \
  --query 'agentSummaries[?agentName==`agent-linkme-ai-poc`].agentId' \
  --output text)

echo "Agent ID: $AGENT_ID"

# 3. Knowledge Base sync (trigger document ingestion)
KB_ID=$(AWS_PROFILE=commit-ai-sandbox-01 \
  aws bedrock-agent list-knowledge-bases \
  --region us-west-2 \
  --query 'knowledgeBaseSummaries[?name==`kb-linkme-ai-poc`].knowledgeBaseId' \
  --output text)

DS_ID=$(AWS_PROFILE=commit-ai-sandbox-01 \
  aws bedrock-agent list-data-sources \
  --region us-west-2 \
  --knowledge-base-id "$KB_ID" \
  --query 'dataSourceSummaries[0].dataSourceId' --output text)

AWS_PROFILE=commit-ai-sandbox-01 \
aws bedrock-agent start-ingestion-job \
  --region us-west-2 \
  --knowledge-base-id "$KB_ID" \
  --data-source-id "$DS_ID"

# 4. Verify SQS queues exist
AWS_PROFILE=commit-ai-sandbox-01 \
aws sqs list-queues \
  --region us-west-2 \
  --queue-name-prefix "sqs-linkme-ai-poc" \
  --output table

# 5. Verify MemoryDB cluster
AWS_PROFILE=commit-ai-sandbox-01 \
aws memorydb describe-clusters \
  --region us-west-2 \
  --cluster-name "mdb-linkme-ai-poc-redis" \
  --query 'Clusters[0].{Name:Name,Status:Status,Endpoint:ClusterEndpoint.Address}' \
  --output table
# Expected: Status = available
```

---

## Dependency Order Summary

```
Bootstrap (CodeCommit — S3 state bucket auto-created by Terragrunt)  ~2 min  (manual)
    │
    ▼
Phase 1: terragrunt run --all apply                                  ~15 min
    vpc + app/ai + messaging/cicd
    (MemoryDB takes ~10 min to provision)
    │
    ▼
Phase 2: backend CodeBuild                                          ~12 min  (AgentCore READY)
    │
    ▼
Phase 3: E2E verification                                           ~1 min

Total from scratch: ~30 min
```

---

## Subsequent Deployments

For any change after the initial setup, only the affected layer or pipeline needs to run:

```bash
# Infrastructure change — apply all changed layers in DAG order
cd infrastructure/accounts/commit-ai-sandbox-01/us-west-2
terragrunt run --all apply

# Single layer change (faster when only one layer changed)
cd infrastructure/accounts/commit-ai-sandbox-01/us-west-2/messaging
terragrunt apply

# Application code change — trigger the backend pipeline
AWS_PROFILE=commit-ai-sandbox-01 \
aws codebuild start-build --region us-west-2 --project-name linkme-ai-poc-backend-build
```

---

## Enabling Phase 2 Services (when app code arrives)

When the Phase 2 application code is ready:

```hcl
# infrastructure/accounts/commit-ai-sandbox-01/us-west-2/region.hcl

# 1. Enable the ECS services
enable_phase2_services = true
```

Then:

```bash
# Push container images to the 4 Phase 2 ECR repos
for repo in ai-msg-processor ai-service instagram-mock publisher-mock; do
  # docker build + push to linkme-ai-poc-${repo}
  echo "Push image to ECR: linkme-ai-poc-${repo}"
done

# Apply messaging layer
cd infrastructure/accounts/commit-ai-sandbox-01/us-west-2/messaging
terragrunt apply

# Update desired_count from 0 to 1+ in region.hcl, then re-apply
```

### Enable Auto-Scaling (after services are running)

```hcl
# infrastructure/accounts/commit-ai-sandbox-01/us-west-2/region.hcl
enable_autoscaling = true
```

Then apply: `cd messaging && terragrunt apply`

This creates auto-scaling targets and policies for all 4 services:
- **Scale out**: 5x (CPU target tracking, 60s cooldown)
- **Scale in**: 1x (CPU target tracking, 300s cooldown)

---

## Enabling Frontend (when ready)

When the Streamlit frontend is developed, enable it by updating `region.hcl`:

```hcl
# infrastructure/accounts/commit-ai-sandbox-01/us-west-2/region.hcl
enable_frontend = true

codebuild_projects = {
  frontend = {
    description      = "Build and deploy frontend Streamlit application to ECS"
    buildspec        = "streamlit-frontend/buildspec.yml"
    compute_type     = "BUILD_GENERAL1_SMALL"
    environment_type = "LINUX_CONTAINER"
    image            = "aws/codebuild/standard:7.0"
    ecr_repo_key     = "frontend"
  }
  backend = {
    description      = "Build ARM64 backend image and push to ECR for AgentCore Runtime"
    buildspec        = "agentcore-be/buildspec.yml"
    compute_type     = "BUILD_GENERAL1_LARGE"
    environment_type = "ARM_CONTAINER"
    image            = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
    ecr_repo_key     = "backend"
    privileged_mode  = true
  }
}
```

Then apply: `terragrunt run --all apply`

This creates the ALB, frontend SG, ECS task role, frontend log group, and frontend CodeBuild project.

---

## Enabling Lambda Preprocessor (when app code is ready)

```hcl
# infrastructure/accounts/commit-ai-sandbox-01/us-west-2/region.hcl
enable_preprocessor = true
```

Then apply: `cd ai && terragrunt apply`

This creates the Lambda function (with placeholder code), S3 event trigger, CloudWatch log group, VPC security group, and IAM role.

---

## Teardown (reverse order)

```bash
# 1. Delete AgentCore runtime (not managed by Terraform)
RUNTIME_ID=$(AWS_PROFILE=commit-ai-sandbox-01 \
  aws bedrock-agentcore-control list-agent-runtimes \
  --region us-west-2 --query 'agentRuntimes[0].agentRuntimeId' --output text)
AWS_PROFILE=commit-ai-sandbox-01 \
aws bedrock-agentcore-control delete-agent-runtime \
  --region us-west-2 --agent-runtime-id "$RUNTIME_ID"

# 2. Scale down Phase 2 ECS services (if enabled)
for svc in ai-msg-processor ai-service instagram-mock publisher-mock; do
  AWS_PROFILE=commit-ai-sandbox-01 \
  aws ecs update-service --region us-west-2 \
    --cluster ecs-linkme-ai-poc-cluster \
    --service "linkme-ai-poc-${svc}" \
    --desired-count 0 2>/dev/null
done

# 3. Empty S3 buckets (Terraform cannot destroy non-empty buckets)
for bucket in \
  linkme-ai-poc-codebuild-artifacts-095128162384 \
  linkme-ai-poc-s3-access-logs-095128162384 \
  linkme-ai-poc-kb-data-095128162384 \
  linkme-ai-poc-kb-data-095128162384-logs; do
  AWS_PROFILE=commit-ai-sandbox-01 \
  aws s3 rm "s3://${bucket}" --recursive 2>/dev/null
done

# 4. Terraform destroy in reverse DAG order
cd infrastructure/accounts/commit-ai-sandbox-01/us-west-2

cd messaging && terragrunt destroy && cd ..
cd cicd      && terragrunt destroy && cd ..
cd app       && terragrunt destroy && cd ..
cd ai        && terragrunt destroy && cd ..
cd vpc       && terragrunt destroy && cd ..

# 5. Bootstrap cleanup (optional — permanent deletion)
AWS_PROFILE=commit-ai-sandbox-01 \
aws s3 rb s3://terraform-states-095128162384-us-west-2 --force
AWS_PROFILE=commit-ai-sandbox-01 \
aws codecommit delete-repository \
  --region us-west-2 --repository-name linkme-ai-poc
```
