# interactive

Phase 1 interactive flow for the LinkMe AI POC.

## Contents

| Resource | Purpose |
|---|---|
| `aws_bedrockagentcore_agent_runtime.phase1` | Conversational creator-setup agent (Strands SDK, ARM64 container) |
| `aws_lambda_function.api` + `aws_lambda_function_url.api` | Slim REST surface — profile/document CRUD, submit-question (enqueues to SQS incoming), answer polling (reads DDB results with fallback to messages) |
| `aws_lambda_function.preprocessor` + `aws_s3_bucket_notification.raw_uploads` | S3-event-driven preprocessor — Nova Lite for images/video, PDF/URL parser, writes normalized text to `linkme-poc-kb-source`, kicks off Bedrock KB ingestion |
| `aws_s3_bucket.ui` + website + public-read policy | Static UI host (Setup Assistant + Live Test tabs) |
| `aws_dynamodb_table.this["profiles|cache|messages|semantic_cache"]` | Phase 1 interactive state |

## Dependencies

- `vpc` — private subnets
- `app` — AgentCore ECR repo URI + ECS task execution role
- `ai` — Bedrock Knowledge Base ID + `linkme-poc-kb-source` + `linkme-poc-raw-uploads` bucket names/ARNs
- `messaging` — SQS incoming URL/ARN + DDB results table (for API poll fallback)

## Feature flags

| Flag | Default | Effect |
|---|---|---|
| `enable_api_lambda` | true | Create API Lambda + Function URL |
| `enable_preprocessor` | true | Create Preprocessing Lambda + S3 event notification |
| `enable_agentcore_runtime` | true | Create AgentCore Runtime + IAM |
| `enable_ui_bucket` | true | Create UI S3 bucket |

## Deploy flow

CodeBuild projects `agentcore` (image) and built-in `linkme-poc-api`/`linkme-poc-preprocessing` (zip) build and deploy via CodeBuild → ECR/S3 → `aws lambda update-function-code` / AgentCore runtime update.
