# LinkMe AI POC — Project Description

## Overview

LinkMe AI is a multi-tenant AI-powered conversation platform for creators (influencers). Each creator configures an AI agent with custom goals, tone, output-schema rules, and a tenant-scoped knowledge base. The system generates personalized answers to incoming fan messages using Amazon Bedrock (Knowledge Bases + Claude LLMs + Nova multimodal + AgentCore Runtime), a SageMaker-hosted embedding endpoint, a MemoryDB-backed semantic cache, DynamoDB, SQS, and ECS Fargate.

The POC is organized in two phases that share a single infrastructure footprint:

- **Phase 1** — Creator Setup: interactive knowledge-base construction driven by an AgentCore Runtime and a thin API Lambda. Raw uploads (PDFs, images, videos, URLs) are preprocessed by a Lambda that feeds the Bedrock Knowledge Base.
- **Phase 2** — Message Pipeline / Simulator: an S3-driven pipeline that ingests up to 500,000 messages from a 1-minute input window and completes full end-to-end processing within ~20 minutes, using ECS Fargate services for cache and LLM stages and DynamoDB as the result store.

The infrastructure is deployed to the **commit-ai-sandbox-01** AWS account (`095128162384`) in the **us-west-2** region using Terraform and Terragrunt.

**Project name**: `linkme-ai`
**Environment**: `poc`
**Repository**: `linkme-ai-poc`
**Terraform root**: `infrastructure/`

---

## Phase 1 — Creator Setup, Knowledge Base & AgentCore Runtime

> Reference diagram: `docs/images/LinkMe-POC-Phase1.png`

Phase 1 establishes the creator's profile and tenant-scoped knowledge base. A creator interacts with the system either through the web UI (S3-hosted) or conversationally through the AgentCore Runtime. Raw uploads land in S3 and are processed by a Lambda that extracts text (via Nova for multimodal content) and triggers Bedrock Knowledge Base ingestion.

### Architecture

```
Creator / Admin (browser)
      │   HTTPS
      ▼
┌───────────────────────┐   ┌───────────────────────────┐   ┌──────────────────────────────┐
│  UI (S3 static site)  │   │  API Lambda (Function URL)│   │  AgentCore Runtime (Strands)  │
│  linkme-poc-ui        │   │  linkme-poc-api           │   │  Bedrock AgentCore + Claude  │
└──────────┬────────────┘   └────────────┬──────────────┘   └──────────────┬───────────────┘
           │   profile / doc CRUD        │                                 │ conversational tools
           │   raw file upload           │                                 │ preview answer
           │   submit question           │                                 │ KB sync
           ▼                             ▼                                 ▼
      DDB profiles · DDB messages · DDB cache · S3 raw-uploads · S3 kb-source · Bedrock KB

S3 raw-uploads ──(S3 ObjectCreated)──► Preprocessing Lambda (linkme-poc-preprocessing)
                                         │
                                         ├─ Bedrock Nova Lite   (image/video/url → text)
                                         ├─ PDF / URL parser    (text extraction)
                                         ├─ S3 put_object       (kb-source / {tenant}/*)
                                         └─ Bedrock KB          (StartIngestionJob)
                                                 │
                                                 ▼
                                    Bedrock Knowledge Base (S0WOFNAVDL)
                                      ├─ Titan Embeddings V2 (1024-dim)
                                      └─ S3 Vectors (vector bucket + index)
```

### Components

| Component | AWS Service | Purpose |
|---|---|---|
| **UI** | Amazon S3 static website | Creator console — Setup Assistant and Live Test tabs. Static HTML/JS; no server-side rendering. |
| **API Lambda** | AWS Lambda + Function URL | Slim REST surface — profile/document CRUD, raw-file upload URL minting, submit-question (enqueue to SQS Incoming), answer polling (DDB Results + DDB Messages fallback). |
| **AgentCore Runtime** | Amazon Bedrock AgentCore Runtime | Conversational creator setup. Strands SDK agent on an ARM64 container; tools mutate profile/KB via DDB/S3/Bedrock calls. Preview uses a self-contained code path that does not cross into the pipeline. |
| **Preprocessing Lambda** | AWS Lambda (S3-event-driven) | Parses PDFs/URLs, invokes Nova Lite for image/video content, writes normalized text to the KB-source bucket under the tenant prefix, starts a Bedrock KB ingestion job. |
| **Multimodal Processor** | Amazon Bedrock Nova Lite | Image description and short-video transcription. Output text is written to the KB-source bucket for subsequent KB ingestion. |
| **Knowledge Base** | Amazon Bedrock Knowledge Base | Tenant-aware RAG store. Metadata filter on `tenant_id` in every retrieval; single KB shared across tenants. |
| **KB Vector Store** | Amazon S3 Vectors | Vector bucket + index (1024 dimensions, cosine). No OpenSearch Serverless minimum-cost floor. |
| **KB Embeddings** | Amazon Titan Embeddings V2 | Used exclusively by the Bedrock-managed KB ingestion path (1024-dim). Not used by the semantic cache. |
| **Creator profile store** | Amazon DynamoDB (`ddb-linkme-poc-profiles`) | Creator profile JSON keyed by `tenant_id`. |
| **Messages store** | Amazon DynamoDB (`ddb-linkme-poc-messages`) | Legacy per-message status used by the UI "Live Test" poll (coexists with the new Results table during transition). |
| **Raw uploads store** | Amazon S3 (`linkme-poc-raw-uploads`) | Pre-preprocessing raw files. |
| **KB source store** | Amazon S3 (`linkme-poc-kb-source`) | Normalized text documents per tenant, read by Bedrock KB ingestion. |

### Data Flow

1. **Creator interaction**: a creator either uses the UI (HTTPS → API Lambda) or talks to the AgentCore Runtime to build a profile and upload raw content.
2. **Raw ingestion**: raw files land in `linkme-poc-raw-uploads`; metadata ties the object to a `tenant_id`.
3. **Preprocessing**: the S3 event triggers the Preprocessing Lambda, which parses PDFs and URLs directly and sends images/video to Nova Lite for text extraction.
4. **KB ingestion**: normalized text is written to `linkme-poc-kb-source` under a tenant prefix, and `StartIngestionJob` is called on the Bedrock KB. Titan V2 embeddings (1024-dim) populate S3 Vectors.
5. **Profile completion**: the creator (via AgentCore) confirms the profile; the profile JSON is persisted to DDB Profiles.
6. **Preview**: the UI calls the API Lambda's `POST /leads/{id}/preview`, which uses a self-contained preview path (profile + KB retrieval + Bedrock LLM) with no dependency on the Phase 2 pipeline.

### Key Design Decisions (Phase 1)

- **AgentCore Runtime is fully Terraform-managed** (`aws_bedrockagentcore_runtime` + endpoint + alias + IAM role). No manual deploys, no `null_resource` wrappers — the only human step is image push via CodeBuild.
- **Bedrock KB uses Titan V2 (1024-dim)**. This is separate from the semantic cache (Phase 2) and requires no dimensional alignment — they are two independent retrieval systems.
- **Nova Lite** handles image and short-video text extraction; **Titan V2** handles vector embedding. Single embedding model for the KB path.
- **Multi-tenant isolation** is enforced via (a) S3 key prefix per tenant in the KB-source bucket and (b) metadata filter on `tenant_id` in every Bedrock KB retrieval.
- **UI + API Lambda + AgentCore coexist**. The API Lambda is kept thin (CRUD + submit + poll); AgentCore owns the conversational flow. Both share the same DDB Profiles table.
- **Preview is self-contained**: `POST /leads/{id}/preview` never touches the Phase 2 pipeline; there is a strict code boundary between the two components so simulator load cannot affect interactive latency.

---

## Phase 2 — AI Message Processing Pipeline & 500K Simulator

> Reference diagram: `docs/images/LinkMe-POC-Phase2.png`

Phase 2 is an S3-driven pipeline that ingests large batches of messages into SQS, processes them through two ECS Fargate services (cache + LLM), and writes all results to DynamoDB. The design target is 500,000 messages from a 1-minute input window, fully processed end-to-end within ~20 minutes, with a 65–85 % semantic-cache hit rate.

### Architecture

```
                                         ┌────────────────┐
                                         │  CloudWatch    │
                                         │  logs + EMF    │
                                         │  metrics + dash│
                                         │  + alarms      │
                                         └────────┬───────┘
                                                  │
S3 input-messages ──► messages-pusher ──► SQS incoming ──► cache-service ──► DDB results
(JSONL batches,        (ECS Fargate Task,    (standard)    (ECS Fargate     (Final answer)
 run_id prefix)         operator-triggered                  Service, HPA)
                        via aws ecs run-task)                   │ miss
                                                                ▼
                                                       SQS ai-processing.fifo
                                                        (per-lead group id)
                                                                │
                                                                ▼
                                                          llm-service  ──► DDB results
                                                         (ECS Fargate        + cache write-back
                                                          Service, HPA)      + MemoryDB write-back
                                                                │
                                                       ┌────────┴─────────┐
                                                       ▼                  ▼
                                              Bedrock KB (RAG,     Bedrock LLM (Haiku/Sonnet
                                               tenant filter)       via US CRIS inference profile)

Shared state:
  • MemoryDB for Redis (HNSW 768-dim, cosine)           — used by cache-service + llm-service
  • SageMaker endpoint linkme-poc-embedding (bge-base-en-v1.5, 768-dim) — embeddings for cache only
  • DDB profiles (Phase 1 shared) · DDB cache (exact hash) · DDB results (Phase 2 write target)
```

### Components

| Component | AWS Service | Purpose |
|---|---|---|
| **Messages Pusher** | Amazon ECS on AWS Fargate (task-def only, run-task triggered) | One-shot simulator driver. Reads JSONL batches from `S3 input-messages`, fans out across N pod indices, sends to SQS `incoming` via `SendMessageBatch`. No running service. |
| **Cache Service** | Amazon ECS on AWS Fargate (long-running Service) | Consumes SQS `incoming`. Exact hash lookup (DDB Cache) → embed via SageMaker → semantic search in MemoryDB (HNSW 768-dim, cosine). Hit: write DDB Results. Miss: send to SQS `ai-processing.fifo`. |
| **LLM Service** | Amazon ECS on AWS Fargate (long-running Service) | Consumes SQS `ai-processing.fifo` (FIFO, per-lead group id). Loads profile (DDB Profiles), retrieves from Bedrock KB, batches per-lead questions, invokes Bedrock (Haiku or Sonnet via US CRIS). Writes DDB Results + writes back exact cache (DDB Cache) + writes back semantic entry (MemoryDB). |
| **Incoming queue** | Amazon SQS Standard (`sqs-linkme-ai-poc-incoming`) | High-throughput ingestion from messages-pusher to cache-service. 20 s long-poll, 120 s visibility, DLQ with `maxReceiveCount=5`. |
| **AI Processing queue** | Amazon SQS FIFO (`sqs-linkme-ai-poc-ai-processing.fifo`) | Cache-miss → LLM with strict per-creator ordering (`MessageGroupId = lead_id`). Per-message dedup. Separate FIFO DLQ. |
| **Semantic cache / rate-limit store** | Amazon MemoryDB for Redis | HNSW vector search (768-dim) and TTL counters for rate limiting. Redis 7.1+ with native `FT.*` commands. `db.t4g.small` baseline; `db.t4g.medium` at burst per Scaling Strategy. |
| **Embedding endpoint** | Amazon SageMaker Real-time Endpoint (`linkme-poc-embedding`) | Self-hosted `bge-base-en-v1.5` at 768 dimensions. Serves embedding requests for the semantic cache only. `ml.t2.medium x1` baseline; scaled per Scaling Strategy for simulation runs. |
| **Results store** | Amazon DynamoDB (`ddb-linkme-ai-poc-results`) | Final answer store. PK `message_id`, GSI1 `run_id` + `processed_at`, PPR billing, PITR on, TTL via `expires_at`. Both cache-service (hits) and llm-service (misses) write here. |
| **Exact cache store** | Amazon DynamoDB (`ddb-linkme-poc-cache`) | SHA-256 keyed exact cache. Read by cache-service, written by llm-service. |
| **Simulator input store** | Amazon S3 (`linkme-ai-poc-input-messages`) | JSONL batches under `messages/{run_id}/batch-*.jsonl`. 7-day lifecycle. |
| **Bedrock LLMs** | Amazon Bedrock (Claude Haiku 4.5, Claude Sonnet 4/4.5) via US CRIS inference profiles | Generates answers on cache miss. Routing centroid selects the cheaper Haiku for simple/medium and Sonnet for complex. |
| **CloudWatch** | Amazon CloudWatch | Single dashboard `dash-linkme-ai-poc-simulator`; alarms for DLQ depth, queue age, E2E p95, DDB throttles. All custom metrics emitted as **Embedded Metric Format (EMF)** log lines — no `PutMetricData` calls. |

### Data Flow

1. **Simulator setup**: operator uploads JSONL batches to `s3://linkme-ai-poc-input-messages/messages/{run_id}/batch-*.jsonl` (one `IncomingMessage` JSON per line).
2. **Ingestion**: operator runs `scripts/run_simulation.ps1`, which calls `aws ecs run-task --task-definition $(messages_pusher_task_definition_arn) --cluster $(ecs_cluster_name) --count $POD_COUNT` with per-pod `RUN_ID`, `POD_INDEX`, `POD_COUNT` overrides. Each task lists its slice of S3 objects and sends batches of 10 to SQS `incoming`.
3. **Cache lookup**: `cache-service` long-polls `incoming` (20 s), runs exact-hash lookup on DDB Cache, embeds via SageMaker when needed, runs `FT.SEARCH` in MemoryDB. On hit (exact ≥ 0.92 or semantic ≥ 0.92 similarity, borderline 0.82–0.92) it writes the result to DDB Results tagged with the cache tier.
4. **Miss routing**: on miss, `cache-service` sends the message to SQS `ai-processing.fifo` with `MessageGroupId = lead_id` and `MessageDeduplicationId = message_id`.
5. **LLM path**: `llm-service` consumes the FIFO queue, loads the creator profile from DDB Profiles, retrieves tenant-filtered context from the Bedrock KB, batches up to 10 questions per lead into one invocation, and calls Bedrock via the US CRIS inference profile.
6. **Result persistence**: `llm-service` writes the final answer to DDB Results, writes back to the exact cache (DDB) and the semantic cache (MemoryDB HSET + vector), emits EMF metrics, and deletes the SQS message.
7. **Observability**: every log line carries `correlation_id = {run_id}:{message_id}` propagated through SQS `MessageAttributes`. Every stage boundary (`sqs_receive`, `exact_cache`, `embedding`, `semantic_search`, `kb_retrieve`, `bedrock_invoke`, `cache_writeback`, `ddb_results_write`) emits an EMF metric, and the dashboard renders per-stage p50/p95 latency and cache-tier mix per `run_id`.

### Key Design Decisions (Phase 2)

- **Embedding ownership is split by design**. The semantic cache uses the SageMaker endpoint `linkme-poc-embedding` (`bge-base-en-v1.5`, 768-dim). The Bedrock KB uses Titan Embeddings V2 (1024-dim). These are two independent retrieval systems — there is no vector-dim alignment requirement and no reindexing needed.
- **Compute is ECS Fargate ARM64 (Graviton)** for all three pipeline components. No EKS, no Lambda on the hot path.
- **FIFO ordering only where it matters**: per-creator ordering via `MessageGroupId = lead_id` on the `ai-processing.fifo` queue; ingestion uses a standard queue for throughput.
- **Bedrock throttling is handled by design**, not monitored-and-hoped-for:
  - Three-tier semantic cache absorbs 65–85 % of traffic before it reaches Bedrock.
  - Per-lead FIFO batching packs up to 10 questions per invocation, reducing Bedrock calls ~10×.
  - US Cross-Region Inference profiles (Haiku + Sonnet) distribute traffic across multiple regions.
  - `llm-service` implements circuit-break-with-backoff on `ThrottlingException` and falls back from Sonnet to Haiku on persistent throttling.
- **Messages-pusher throughput target**: ingest 500K messages from the 1-minute input window within the ~20-minute simulation budget. Baseline parallelism: 10 Fargate tasks × ~34 concurrent `SendMessageBatch(10)` per task → ~8,334 msg/sec → 500K in ~60 s, leaving ~19 minutes of processing budget. `POD_COUNT` and per-task `SEND_WORKERS` are env-driven for any future gap.
- **SageMaker throughput is intentionally small for POC cost** (`ml.t2.medium x1`, ~$41/mo). Scaled per [`SCALING_STRATEGY.md`](SCALING_STRATEGY.md) and [`COST_MODEL.md`](COST_MODEL.md) during simulation runs (`ml.c6i.large x2` baseline, auto-scale to 8).
- **DDB Results uses PAY_PER_REQUEST**: absorbs the burst without pre-provisioned capacity management; UUID `message_id` (random PK) avoids hot-partition throttling.
- **All custom metrics use EMF** (embedded-metric-format log lines). No `PutMetricData` calls — lower cost and no quota constraint on the simulator.
- **Component boundary strictly enforced**: Phase 1 AgentCore never imports Phase 2 libraries; Phase 2 services never import the AgentCore code. Shared primitives live in `src/common/`.

---

## AWS Services Summary

| Service | Phase | Purpose |
|---|---|---|
| **Amazon Bedrock (AgentCore Runtime)** | 1 | Conversational creator-setup agent (Strands SDK on ARM64 container) |
| **Amazon Bedrock (Knowledge Base)** | 1, 2 | Tenant-filtered RAG store backed by S3 Vectors |
| **Amazon S3 Vectors** | 1, 2 | Vector bucket + index for the Bedrock KB (1024-dim) |
| **Amazon Bedrock (Claude Haiku / Sonnet)** | 2 | LLM inference on cache miss, via US CRIS inference profiles |
| **Amazon Bedrock (Nova Lite)** | 1 | Image/short-video text extraction during preprocessing |
| **Amazon Bedrock (Titan Embed V2)** | 1 | Embeddings used exclusively by the Bedrock KB ingestion path |
| **Amazon SageMaker Real-time Endpoint** | 2 | Self-hosted `bge-base-en-v1.5` (768-dim) embeddings for the semantic cache |
| **Amazon ECS on AWS Fargate (ARM64)** | 2 | `cache-service` + `llm-service` (long-running) and `messages-pusher` (task-only) |
| **AWS Lambda** | 1 | `linkme-poc-api` + `linkme-poc-preprocessing` |
| **Amazon SQS (standard + FIFO)** | 2 | `incoming` (standard) + `ai-processing.fifo` (FIFO) + DLQs |
| **Amazon DynamoDB** | 1, 2 | `profiles`, `cache`, `messages`, `semantic-cache` (fallback), and `results` (new) |
| **Amazon MemoryDB for Redis** | 2 | Semantic cache HNSW index (768-dim) and rate-limit counters |
| **Amazon S3** | 1, 2 | `kb-source`, `raw-uploads`, `ui` (Phase 1), `input-messages` (Phase 2) |
| **Amazon CloudWatch** | 1, 2 | Logs + EMF metrics + dashboard `dash-linkme-ai-poc-simulator` + alarms |
| **Amazon ECR** | 1, 2 | Container images for `agentcore`, `messages-pusher`, `cache-service`, `llm-service`, `backend` |
| **AWS CodeBuild + CodeCommit** | 1, 2 | CI/CD — one project per image; single deployment path from `git push` to ECS / Lambda / AgentCore update |
| **AWS KMS** | 1, 2 | Encryption for ECR images, CloudWatch logs, SSM parameters |
| **AWS IAM** | 1, 2 | Least-privilege roles — per-Lambda role, per-ECS-task role, AgentCore execution role, CodeBuild role |

---

## Infrastructure (IaC)

All infrastructure is managed with **Terraform** (`~> 6.0` AWS provider) and **Terragrunt**, following a layered architecture. There is no manual console step, no `null_resource` wrapper, and no out-of-band shell deploy. Every deployed resource — including the AgentCore Runtime — is a Terraform-declared resource with a plannable diff.

### Deployment Target

| Setting | Value |
|---|---|
| AWS Account | `commit-ai-sandbox-01` (`095128162384`) |
| Region | `us-west-2` |
| Environment | `poc` |
| Project Name | `linkme-ai` |
| AWS Provider | `~> 6.0` |
| Terraform root | `infrastructure/` |
| Terragrunt entry point | `infrastructure/accounts/commit-ai-sandbox-01/us-west-2/` |

### Layer Dependency Graph

```
vpc  (no dependencies)
 ├──► app         (depends on vpc)
 │     ├──► cicd         (depends on app)
 │     ├──► workloads    (depends on app + ai + messaging)
 │     └──► interactive  (depends on app + ai + messaging)
 ├──► ai          (depends on vpc)
 │     ├──► workloads    (depends on ai)
 │     └──► interactive  (depends on ai)
 └──► messaging   (depends on vpc)
       ├──► workloads    (depends on messaging)
       └──► interactive  (depends on messaging)
```

Apply order (Terragrunt `run-all apply`): `vpc` → `app` + `ai` + `messaging` in parallel → `workloads` + `interactive` + `cicd` in parallel.

### Layer Breakdown

| Layer | Purpose | Key Resources |
|---|---|---|
| **vpc** | Network foundation | VPC, 6 subnets (public / private-app / private-db × 2 AZs), NAT Gateway, IGW, route tables, VPC flow logs, VPC endpoints (S3 gateway + interface endpoints for Bedrock, ECR, CloudWatch Logs, SQS, SageMaker Runtime, DynamoDB gateway) |
| **app** | Shared compute & registry | ECS Cluster (`linkme-ai-poc`), Fargate capacity providers, ECR repos (`backend`, `agentcore`, `messages-pusher`, `cache-service`, `llm-service`), shared KMS keys, base IAM roles (`ecs_task_execution_role`), CloudWatch log groups, optional ALB/WAF gated by `enable_frontend` |
| **ai** | Bedrock AI + self-hosted embeddings | Bedrock Knowledge Base (S0WOFNAVDL) + S3 Vectors bucket + index, Bedrock Agent + alias (preview path), SageMaker model + endpoint config + endpoint (`linkme-poc-embedding`, 768-dim `bge-base-en-v1.5`), S3 `kb-source`, S3 `raw-uploads`, IAM roles |
| **messaging** | Phase 2 data plane | SQS `incoming` + DLQ, SQS `ai-processing.fifo` + FIFO DLQ, DDB `results`, S3 `input-messages`, MemoryDB for Redis (`db.t4g.small` baseline) + subnet group + parameter group, MemoryDB SG, CloudWatch dashboard `dash-linkme-ai-poc-simulator`, CloudWatch alarms |
| **interactive** | Phase 1 interactive flow (fully TF-managed) | API Lambda `linkme-poc-api` + Function URL + IAM, Preprocessing Lambda `linkme-poc-preprocessing` + S3 event notification + IAM, AgentCore Runtime (`aws_bedrockagentcore_runtime` + endpoint + alias + IAM), S3 `ui` bucket + website config, imported DDB `profiles` / `cache` / `messages` / `semantic-cache` |
| **workloads** | Phase 2 simulator compute | ECS task definitions for `cache-service` / `llm-service` / `messages-pusher`, ECS services for `cache-service` + `llm-service` (not `messages-pusher`), Application Auto Scaling targets + policies (target-tracking on SQS queue depth + step-scaling fallback), task IAM roles (per service, trust `ecs-tasks.amazonaws.com`), task security group + MemoryDB ingress rule, CloudWatch log groups `/ecs/linkme-ai/poc/<service>` |
| **cicd** | Build + deploy pipelines | CodeBuild projects (`backend`, `agentcore`, `messages-pusher`, `cache-service`, `llm-service`), S3 artefacts bucket + lifecycle, IAM roles per project with `iam:PassRole` scoped to the ECS task roles and AgentCore execution role, CloudWatch log groups |

### Feature Flags

| Flag | Layer | Default | Purpose |
|---|---|---|---|
| `enable_frontend` | app | `false` | ALB + frontend SG + frontend ECS task role — not needed for POC, gated off |
| `backend_type` | app | `agentcore` | Selects backend compute: `agentcore` / `ecs` / `lambda` / `none`. POC uses `agentcore`. |
| `enable_knowledge_base` | ai | `true` | Bedrock KB + S3 Vectors + data source |
| `enable_agent` | ai | `true` | Bedrock Agent + alias for the preview path |
| `enable_preprocessor` | interactive | `true` | Preprocessing Lambda (S3 event-driven) |
| `enable_agentcore_runtime` | interactive | `true` | `aws_bedrockagentcore_runtime` + endpoint + alias |
| `enable_waf` | app | `false` | WAFv2 on the ALB — off for POC |
| `enable_messaging` | messaging | `true` | SQS queues + MemoryDB + `results` table |
| `enable_memorydb` | messaging | `true` | MemoryDB cluster + SG + parameter group |
| `enable_workloads` | workloads | `true` | ECS task defs + services + auto-scaling |
| `enable_autoscaling` | workloads | `true` | Application Auto Scaling on ECS services (baseline `max_capacity=desired_count`; operator raises via CLI for burst) |

### Backend Type

The `app` layer supports flexible backend types via `var.backend_type`:

| Type | Description | Phase |
|---|---|---|
| `agentcore` | Amazon Bedrock AgentCore Runtime — IAM + SG resources in `app`, runtime itself in `interactive` (`aws_bedrockagentcore_runtime`) | 1 |
| `ecs` | Self-managed ECS Fargate service in the `app` layer (not used for POC — the simulator services live in `workloads`) | — |
| `lambda` | Container-image Lambda in the `app` layer | — |
| `none` | No backend compute in `app` | — |

### Brownfield Resources — Imported, Not Re-Created

Existing shared resources are adopted via `terraform import` so there is no destructive replacement of production data. DevOps runs the documented imports during the first apply cycle:

| Resource | Terraform Address (example) | Import Command |
|---|---|---|
| Bedrock KB `S0WOFNAVDL` | `module.ai.aws_bedrockagent_knowledge_base.this` | `terragrunt import module.ai.aws_bedrockagent_knowledge_base.this S0WOFNAVDL` |
| SageMaker endpoint `linkme-poc-embedding` | `module.ai.aws_sagemaker_endpoint.embedding` | `terragrunt import module.ai.aws_sagemaker_endpoint.embedding linkme-poc-embedding` |
| MemoryDB cluster `linkme-poc-cache` | `module.messaging.aws_memorydb_cluster.this` | `terragrunt import module.messaging.aws_memorydb_cluster.this linkme-poc-cache` |
| DDB `ddb-linkme-poc-profiles` | `module.interactive.aws_dynamodb_table.profiles` | `terragrunt import module.interactive.aws_dynamodb_table.profiles ddb-linkme-poc-profiles` |
| DDB `ddb-linkme-poc-cache` | `module.interactive.aws_dynamodb_table.cache` | `terragrunt import module.interactive.aws_dynamodb_table.cache ddb-linkme-poc-cache` |
| DDB `ddb-linkme-poc-messages` | `module.interactive.aws_dynamodb_table.messages` | `terragrunt import module.interactive.aws_dynamodb_table.messages ddb-linkme-poc-messages` |
| S3 `linkme-poc-kb-source` | `module.ai.aws_s3_bucket.kb_source` | `terragrunt import module.ai.aws_s3_bucket.kb_source linkme-poc-kb-source` |
| S3 `linkme-poc-raw-uploads` | `module.ai.aws_s3_bucket.raw_uploads` | `terragrunt import module.ai.aws_s3_bucket.raw_uploads linkme-poc-raw-uploads` |
| S3 `linkme-poc-ui` | `module.interactive.aws_s3_bucket.ui` | `terragrunt import module.interactive.aws_s3_bucket.ui linkme-poc-ui` |
| Preprocessing Lambda | `module.interactive.aws_lambda_function.preprocessing` | `terragrunt import module.interactive.aws_lambda_function.preprocessing linkme-poc-preprocessing` |
| AgentCore Runtime | `module.interactive.aws_bedrockagentcore_runtime.phase1_agent` | `terragrunt import module.interactive.aws_bedrockagentcore_runtime.phase1_agent <runtime-arn>` |

After every import, `terragrunt plan` must show a zero diff on the imported resource. Any non-trivial diff is resolved by updating the Terraform input to match the deployed reality — never the other way around.

### Bedrock Model Access

The `app` layer IAM policies grant access to:

| Model | Model ID / Profile |
|---|---|
| Claude Opus 4.6 | `anthropic.claude-opus-4-6-v1` |
| Claude Sonnet 4.6 | `anthropic.claude-sonnet-4-6` |
| Claude Sonnet 4.5 | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (US CRIS profile) |
| Claude Haiku 4.5 | `us.anthropic.claude-haiku-4-5-20251001-v1:0` (US CRIS profile) |
| Amazon Titan Embeddings V2 | `amazon.titan-embed-text-v2:0` |
| Amazon Nova Lite | `us.amazon.nova-lite-v1:0` (US CRIS profile) |

### Deployment Flow (single canonical path, no alternatives)

```
Developer ──► git push ──► CodeCommit ──► CodeBuild (per component)
                                                 │
                                                 │  1. docker buildx build --platform linux/arm64 --tag :{git-sha}
                                                 │  2. docker push   ECR :{git-sha}
                                                 │  3. For ECS components:
                                                 │     • aws ecs register-task-definition  (pins :{git-sha})
                                                 │     • long-running services:
                                                 │         aws ecs update-service --force-new-deployment
                                                 │     • one-shot messages-pusher:
                                                 │         (stop here — operator runs via scripts/run_simulation.ps1)
                                                 │  4. For Lambda components:
                                                 │     • aws s3 cp <zip> s3://<artifacts_bucket>/<key>
                                                 │     • aws lambda update-function-code --s3-bucket ... --s3-key ...
                                                 │  5. For AgentCore:
                                                 │     • terragrunt apply -target=module.interactive -var agentcore_image_uri=<new>
                                                 ▼
                                        ECS / Lambda / AgentCore runtime updates
                                        (ECS service rolling deploy with deployment circuit breaker + rollback)
```

Rules enforced across every component:

- Images are only built and pushed by CodeBuild. No local `docker push`.
- Every image is tagged with an immutable `:{git-sha}`. There is no `:latest` tag.
- Every deploy produces a new ECS task-definition revision — existing revisions are never mutated.
- All resource names and ARNs consumed by buildspecs and operator scripts are read from Terraform outputs (`terragrunt output -raw <name>`). No hard-coded identifiers.
- ECS services have `deployment_circuit_breaker.rollback = true` so a bad deploy is automatically reverted.

### Performance & Auto-Scaling

- **AI layer** is inherently serverless (Bedrock, S3 Vectors, Lambda) — scales automatically.
- **SageMaker endpoint** is intentionally provisioned small (`ml.t2.medium x1`) for baseline POC cost; scaled to `ml.c6i.large x2` with Application Auto Scaling up to 8 instances during simulation runs, per [`SCALING_STRATEGY.md`](SCALING_STRATEGY.md) and [`COST_MODEL.md`](COST_MODEL.md).
- **ECS services** (`cache-service`, `llm-service`) run at `desired_count=1` baseline with `max_capacity=1`. For simulator bursts the operator flips `max_capacity` (15 for cache, 10 for llm) and `desired_count` (10 for cache, 6 for llm), then restores both after the run. Application Auto Scaling policies:
  - Target-tracking on SQS `ApproximateNumberOfMessagesVisible` (1,000 msgs/task for cache, 50 msgs/task for llm).
  - Step-scaling fallback on the same metric for fast burst response.
- **Messages-pusher** scales by operator-chosen `POD_COUNT` in `aws ecs run-task --count N`.
- **MemoryDB** scales from `db.t4g.small` to `db.t4g.medium` for burst.
- **DynamoDB** tables use PAY_PER_REQUEST, absorbing the burst with no capacity management.
- **SQS** scales transparently; the only tuning is visibility timeout + DLQ `maxReceiveCount=5`.

---

## Application Components (Code)

All application code lives at the repository root under `src/`. Container images are built and pushed by CodeBuild using the per-service `buildspec.yml`.

### Phase 1

| Component | Runtime | Code Path | Description |
|---|---|---|---|
| **Bedrock AgentCore Runtime** | AgentCore (ARM64 container) | `src/phase1_agent/` (+ `Dockerfile.agentcore` + `buildspec.yml` at repo root) | Strands SDK agent with 10 tools (profile CRUD, document upload, ingest, sync KB, preview). Built by CodeBuild project `agentcore`. |
| **API Lambda** | Lambda (Python 3.12) | `src/api/` | Slim REST surface. Submit-question enqueues to SQS `incoming`; poll reads DDB `results` (fallback to DDB `messages`). |
| **Preprocessing Lambda** | Lambda (Python 3.12) | `src/preprocessing/` | S3 event-driven. Parses PDFs/URLs, invokes Nova Lite for images/video, writes to KB-source, starts KB ingestion. |
| **UI** | S3 static website | `src/ui/` | Setup Assistant + Live Test tabs. |

### Phase 2

| Component | Runtime | Code Path | Description |
|---|---|---|---|
| **Messages Pusher** | ECS Fargate Task (task-def only, ARM64) | `src/messages_pusher/` (+ `Dockerfile` + `buildspec.yml`) | S3 list + get → SQS `SendMessageBatch`. Operator-triggered via `aws ecs run-task`. Sharded via `POD_INDEX` / `POD_COUNT` env. |
| **Cache Service** | ECS Fargate Service (ARM64) | `src/cache_service/` (+ `Dockerfile` + `buildspec.yml`) | SQS `incoming` consumer. Exact + semantic cache. Hit → DDB `results`. Miss → SQS `ai-processing.fifo`. |
| **LLM Service** | ECS Fargate Service (ARM64) | `src/llm_service/` (+ `Dockerfile` + `buildspec.yml`) | SQS `ai-processing.fifo` consumer. Profile + KB retrieve + batch prompt + Bedrock invoke + cache write-back + DDB `results`. |
| **Shared libraries** | — | `src/common/` | Config (env-var-driven), schema (Pydantic), logging (structured JSON + correlation_id contextvar), metrics (EMF emit), correlation propagation. |
| **Cache/LLM internals** | — | `src/cache_processor/`, `src/batch_llm/` | Library modules (exact cache, semantic cache, embedder, KB client, prompt builder, routing, Bedrock client) imported by Cache Service and LLM Service. |

---

## Observability Contract

- **Metric namespace**: `LinkMe/POC/Simulator`
- **Metric dimensions**: `Service`, `Stage`, `RunId`, `CacheTier`, `Model`, `Outcome`
- **Emission**: Embedded Metric Format (EMF) log lines — no `PutMetricData` calls.
- **Stages instrumented**: `sqs_receive`, `exact_cache`, `embedding`, `semantic_search`, `sqs_send_ai`, `profile_load`, `kb_retrieve`, `bedrock_invoke`, `cache_writeback`, `ddb_results_write`.
- **Correlation ID**: `{run_id}:{message_id}` propagated via SQS `MessageAttributes.correlation_id` and injected into every log line + metric.
- **Log groups**: `/ecs/linkme-ai/poc/<service>` for ECS workloads, `/aws/lambda/linkme-poc-<func>` for Lambdas. 7-day retention.
- **Dashboard**: `dash-linkme-ai-poc-simulator` — queue depth × 2, oldest-message-age × 2, pushed/sec, cache hit rate by tier, E2E p50/p95/p99, Bedrock p95 by model, ECS task counts + CPU/memory, DDB throttles, DLQ depth.
- **Alarms**: Incoming DLQ > 0 (1 min), AI Processing DLQ > 0 (1 min), Incoming oldest-message-age > 15 min, E2E p95 > 10 s (5 min), DDB write throttle > 0 (1 min), Bedrock `ThrottlingException` count > 5/min.

---

## Open Design Questions

These are the remaining items to lock down during DevOps handoff; they do not block the architecture but must be resolved before the first apply:

1. **Terragrunt promotion** — confirm `infrastructure/` as the committed root and move the current worktree tree into it.
2. **AgentCore provider resources** — confirm the `hashicorp/aws` provider version in `versions.tf` exposes `aws_bedrockagentcore_runtime` (or the closest equivalent). Upgrade the provider if needed; no `null_resource` fallback is permitted.
3. **Existing AgentCore Runtime ARN** — capture from the current deploy and add to the import list.
4. **Budget alarms** — optional CloudWatch billing alarms for simulator burst runs (not required by the architecture, decided by operations).

---

## Remaining Work

The infrastructure scaffolding is specified above. Activation happens when the Terraform tree is in its canonical location, the images are built, and the brownfield imports complete. Tracked items:

| Item | How to Enable | Layer |
|---|---|---|
| Promote Terragrunt tree into `infrastructure/` | One-time repo move + path update | — |
| `terraform import` all brownfield resources | Run the documented commands during the first apply cycle | ai, interactive, messaging |
| Build + push first images | CodeBuild projects run on `git push` | cicd |
| Enable autoscaling target-tracking | `max_capacity` already in Terraform — operator raises via CLI for burst | workloads |
| Decommission legacy CDK stacks | After new stack passes smoke test, `cdk destroy` the old stacks | — |
| Delete legacy SQS queues | `sqs-linkme-poc-ingestion`, `sqs-linkme-poc-batch.fifo`, `sqs-linkme-poc-response` (+ DLQs) | — |
| Delete EKS artefacts from repo | `linkme-ai-poc/k8s/` + `src/*/k8s/` directories and any stale EKS-focused docs | — |
