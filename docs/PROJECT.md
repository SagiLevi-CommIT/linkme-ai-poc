# LinkMe AI POC — Project Description

## Overview

LinkMe AI is an AI-powered social media engagement platform that automates intelligent conversations with leads through Instagram Direct Messages. The system uses Amazon Bedrock agents, knowledge bases, and multimodal AI models to create personalized, context-aware responses based on rich profile data built from documents, images, and videos.

The POC is developed in two phases, each building on the previous one. The infrastructure is deployed to the **commit-ai-sandbox-01** AWS account (`095128162384`) in the **us-west-2** region using Terraform/Terragrunt.

**Project name**: `linkme-ai`
**Environment**: `poc`
**Repository**: `linkme-ai-poc`

---

## Phase 1 — Data Processing, Knowledge Base & Agent Core

> Reference diagram: `docs/images/LinkMe-POC-Phase1.png`

Phase 1 establishes the AI agent's foundational intelligence: ingesting raw data (PDFs, images, videos), building vector-based knowledge bases, and exposing an agent that can answer questions using RAG and web tools.

### Architecture

```
                    Instructions
                    Output Schema  ──►  Amazon Bedrock    prompt instructions +
                    Prompt                Agent Core   ──► output schema        ──► S3 (KB Vectors)
                                            │              Profile document creation
                                            │              RAG (docs, images, videos)
                                            │
                                        ┌───┴───┐
                                        │ Tools │
                                        │ - WebSite URL   │
                                        │ - Web Browser    │
                                        └───────┘
                                            ▲
                                            │ Profile vector creation
                                            │ with Profile document
                                            │
S3 (Input) ──► Lambda (Data PreProcess) ──► Amazon Nova Multimodal ──► Amazon Nova Embeddings ──► S3 (KB Vectors)
               PDF Parser                   Image transcription
                                            Video transcription
```

### Components

| Component | AWS Service | Purpose |
|---|---|---|
| **Agent Core** | Amazon Bedrock Agent (AgentCore runtime) | Central orchestrator. Receives instructions, output schema, and user prompts. Coordinates RAG retrieval, profile creation, and tool use. |
| **Knowledge Base (KB)** | Amazon Bedrock Knowledge Base + S3 Vectors | Stores vector embeddings of profiles, documents, images, and video transcriptions. Uses S3 Vectors as the vector store. |
| **KB Vector Store** | Amazon S3 Vectors | Native S3 vector storage — vector bucket + index with cosine similarity, 1024 dimensions (Titan V2). |
| **KB Data Source** | S3 bucket | Source documents for KB ingestion (PDFs, processed text from images/videos). |
| **Data PreProcessor** | AWS Lambda | Triggered by new uploads to the KB data bucket. Parses PDFs and extracts text for downstream processing. |
| **Multimodal Processor** | Amazon Nova Multimodal | Processes images (description/transcription) and videos (transcription). Produces text representations for embedding. |
| **Embeddings Model** | Amazon Titan Embeddings V2 | Converts text into vector embeddings stored in S3 Vectors via the Bedrock Knowledge Base. |
| **Web Browser Tool** | Bedrock Agent Tool | Allows the agent to browse websites and extract information for profile enrichment or answering questions. |

### Data Flow

1. **Data Ingestion**: Raw files (PDFs, images, videos) are uploaded to the **KB data S3 bucket**.
2. **Preprocessing**: A **Lambda function** triggers on upload, parses PDFs, and routes content to the multimodal processor.
3. **Multimodal Processing**: **Amazon Nova Multimodal** processes images (generates descriptions) and videos (generates transcriptions).
4. **Embedding**: **Amazon Titan Embeddings V2** converts all processed text into 1024-dimensional vector representations.
5. **Knowledge Base Storage**: Vectors are stored in **S3 Vectors** (vector bucket + index), backing the Bedrock Knowledge Base.
6. **Profile Creation**: The agent creates structured **Profile documents** from the ingested data and stores them as vectors.
7. **Agent Interaction**: Users provide **instructions**, **output schema**, and **prompts** to the Agent Core, which:
   - Retrieves relevant context from the Knowledge Base (RAG)
   - Uses web browser tools to fetch additional information
   - Returns structured responses following the output schema

### Key Design Decisions (Phase 1)

- **Amazon Nova** (not Titan) is used for multimodal processing (image/video transcription)
- **Amazon Titan Embeddings V2** is used for vector embeddings (1024 dimensions, float32)
- **S3 Vectors** is used as the vector store — no OpenSearch Serverless overhead or minimum cost
- **Claude Sonnet 4.6** is the default agent foundation model
- The agent receives an explicit **output schema** — responses are structured, not free-form
- **Profile document creation** is a core function — the agent builds and maintains lead profiles
- Web browsing capability enables the agent to enrich profiles with public information
- **No frontend** for Phase 1 POC — backend-only testing via API/CLI
- A "Data Manager into S3?" annotation in the diagram suggests the data management pattern for KB vectors is still being finalized

---

## Phase 2 — AI-Powered Message Processing & Social Media Integration

> Reference diagram: `docs/images/LinkMe-POC-Phase2.png`

Phase 2 builds a production-like message processing pipeline that simulates Instagram DM interactions. It adds queuing, rate limiting, semantic matching, conversation memory, and content publishing capabilities.

### Architecture

```
                                    ┌──────────────────┐
                                    │  Amazon           │
                                    │  CloudWatch       │
                                    └────────┬─────────┘
                                             │
┌──────────┐  conversation   ┌───────────────┴──────┐  AI DM     ┌──────────┐     ┌──────────────┐
│ S3 - KB  │  + bucket id   │  AI Message           │  replies   │ Queue    │     │ Instagram    │
│ Vectors  ├───────────────►│  Processor            ├──────────►│ for AI   │◄───►│ Messages     │
│ Profile  │                │                       │           │ (SQS)    │     │ MockService  │
│ Prompt   │                └───────────┬───────────┘           └──────────┘     └──────────────┘
│ Instr.   │                            │
│ RAG      │                    Answer  │  question
│          │                            │  with meta data
│          │                ┌───────────┴───────────┐           ┌──────────┐     ┌──────────────┐
│          │                │  AI Service            ├──────────►│ Queue    │────►│ Publisher    │
│          │                │                       │           │ for Pub  │     │ MockService  │
│          │                └──┬────────┬───────────┘           │ (SQS)    │     └──────────────┘
│          │                   │        │                       └──────────┘
│          │          RateLimits│        │ Check Semantic Match
│          │                   │        │
│          │         ┌─────────┴──┐   ┌─┴──────────────────┐
│          │         │ MemoryDB   │   │ Amazon Bedrock     │◄── Amazon Titan V2
│          │         │ for Redis  │   │ Knowledge Base     │    (new Q&A vectors)
│          │         │ multi-org  │   └────────────────────┘
│          │         └────────────┘
└──────────┘
                              ┌──────────────────┐
                              │  Amazon           │
                              │  CloudWatch       │
                              └──────────────────┘
```

### Components

| Component | AWS Service | Purpose |
|---|---|---|
| **AI Message Processor** | ECS Fargate / Lambda (TBD) | Receives messages from the AI queue, fetches relevant KB context (conversation + bucket ID), calls AI Service, and sends DM replies back to the queue. |
| **AI Service** | ECS Fargate / Bedrock AgentCore | Core intelligence service. Receives questions with metadata, invokes Bedrock LLM, checks semantic matches, manages cross-org KB lookups, and routes content for publishing. |
| **Amazon Bedrock (LLM)** | Amazon Bedrock (model TBD) | Large Language Model for generating answers. Receives questions with metadata, returns contextual responses. Model selection is TBD for Phase 2. |
| **Bedrock Knowledge Base** | Amazon Bedrock Knowledge Base | Stores and retrieves vector embeddings. Used for semantic matching of incoming questions against known Q&A pairs. Continuously enriched with new interactions. |
| **Amazon Titan V2** | Amazon Titan Embeddings V2 | Generates embeddings for new question-answer pairs to feed back into the Knowledge Base, enabling continuous learning. |
| **Amazon MemoryDB for Redis** | Amazon MemoryDB | Multi-region, multi-organization rate limiting and session state. Prevents abuse and manages conversation context across organizations. |
| **Queue for AI** | Amazon SQS | Decouples Instagram MockService from AI Message Processor. Carries incoming DMs to the processor and outgoing AI replies back. |
| **Queue for Publisher** | Amazon SQS (design TBD) | Decouples AI Service from the Publisher MockService. Carries content to be published. |
| **Instagram Messages MockService** | ECS Fargate / Lambda | Simulates Instagram DM API. Sends incoming messages to the AI queue and receives AI-generated DM replies. Replaced by real Instagram API in production. |
| **Publisher MockService** | ECS Fargate / Lambda | Simulates content publishing. Receives publishing instructions from the AI Service via the publisher queue. Replaced by real publishing APIs in production. |
| **S3 - KB Vectors** | S3 Vectors | Stores Knowledge Base vectors, profile data, prompt instructions, and RAG documents. Shared with Phase 1. |
| **Amazon CloudWatch** | CloudWatch | Monitoring and logging for all services. |

### Data Flow

1. **Message Ingestion**: The **Instagram MockService** receives a simulated DM and pushes it to the **Queue for AI** (SQS).
2. **Message Processing**: The **AI Message Processor** dequeues the message, retrieves the relevant **conversation context + bucket ID** from the S3 KB Vectors store.
3. **AI Inference**: The processor sends the question (with metadata) to the **AI Service**, which:
   a. Queries **Amazon Bedrock** (LLM) for an answer.
   b. Performs a **Semantic Match** check against the **Bedrock Knowledge Base** to find similar past Q&A.
   c. May query **other KBs in other organizations** per lead (cross-org knowledge lookup).
   d. Checks **rate limits** via **MemoryDB for Redis**.
4. **Response Delivery**: The AI Service returns the answer to the AI Message Processor, which sends an **AI DM reply** back through the **Queue for AI** to the Instagram MockService.
5. **Knowledge Base Enrichment**: New question-answer pairs are embedded via **Amazon Titan V2** and stored in the **Bedrock Knowledge Base** for future semantic matching (continuous learning loop).
6. **Content Publishing**: When the AI Service determines content should be published, it sends instructions to the **Queue for Publisher**, which the **Publisher MockService** processes.

### Key Design Decisions (Phase 2)

- **Mock services** for Instagram and Publisher allow development/testing without real API integrations
- **SQS queues** decouple services for resilience and independent scaling
- **Semantic matching** enables the system to reuse successful past answers, reducing LLM calls and improving consistency
- **Continuous learning**: Every Q&A interaction feeds back into the Knowledge Base
- **Multi-org support**: MemoryDB for Redis handles multi-region, multi-organization state — the AI Service can look up KBs across different organizations per lead
- **Rate limiting** at the AI Service level prevents abuse and manages API costs
- **Amazon Titan V2** (not Nova) is used for embeddings in Phase 2 — this may be a deliberate choice for production-grade embeddings or an area to align with Phase 1
- The **LLM model is TBD** for Phase 2 (diagram says "LLM Modal TBD") — final model selection pending benchmarks
- The **Publisher queue** has a question mark in the diagram, suggesting this integration path is still under design

---

## AWS Services Summary

| Service | Phase | Purpose |
|---|---|---|
| **Amazon Bedrock (AgentCore)** | 1, 2 | AI agent orchestration and runtime |
| **Amazon Bedrock (LLM)** | 1, 2 | Language model inference (Claude Sonnet 4.6, etc.) |
| **Amazon Bedrock Knowledge Base** | 1, 2 | RAG vector store and semantic search |
| **Amazon S3 Vectors** | 1, 2 | Vector storage for KB embeddings |
| **Amazon Nova Multimodal** | 1 | Image description and video transcription |
| **Amazon Titan Embeddings V2** | 1, 2 | Text-to-vector embedding for KB |
| **Amazon S3** | 1, 2 | Input data, KB source documents, artifacts |
| **AWS Lambda** | 1 | Data preprocessing (PDF parsing) |
| **Amazon ECS (Fargate)** | 2 | Container hosting for services |
| **Amazon SQS** | 2 | Message queuing (AI queue, Publisher queue) |
| **Amazon MemoryDB for Redis** | 2 | Rate limiting, multi-org session state |
| **Amazon CloudWatch** | 1, 2 | Monitoring and logging |
| **AWS IAM** | 1, 2 | Service roles and least-privilege policies |
| **Amazon ECR** | 1, 2 | Container image registry |
| **Application Load Balancer** | 2 | Frontend traffic routing (when enabled) |
| **AWS KMS** | 1, 2 | Encryption key management |
| **AWS CodeBuild** | 1, 2 | CI/CD build pipelines |

---

## Infrastructure (IaC)

The infrastructure is managed with **Terraform** (`~> 6.0` AWS provider) and **Terragrunt** following a layered architecture.

### Deployment Target

| Setting | Value |
|---|---|
| AWS Account | `commit-ai-sandbox-01` (`095128162384`) |
| Region | `us-west-2` |
| Environment | `poc` |
| Project Name | `linkme-ai` |
| AWS Provider | `~> 6.0` |

### Layer Dependency Graph

```
vpc  (no dependencies)
 ├──► app       (depends on vpc)
 │     ├──► cicd      (depends on app + vpc)
 │     └──► messaging (depends on app + vpc)
 └──► ai        (depends on vpc)
```

### Layer Breakdown

| Layer | Purpose | Key Resources |
|---|---|---|
| **vpc** | Network foundation | VPC, 6 subnets (public/private-app/private-db x 2 AZs), NAT Gateway, IGW, route tables, VPC flow logs, VPC endpoints (S3, Bedrock, ECR, CloudWatch, SQS) |
| **app** | Application compute & access | ECR repos (5), ECS Cluster (Fargate), security groups, IAM roles (ECS execution, AgentCore backend), KMS, CloudWatch logs. ALB/frontend gated by `enable_frontend`. |
| **ai** | Bedrock AI services | S3 Vectors (vector bucket + index), Bedrock Knowledge Base + S3 data source, Bedrock Agent (Sonnet 4.6) + alias, Lambda preprocessor (deferred), IAM roles |
| **messaging** | Phase 2 messaging & services | SQS queues (AI + Publisher) + DLQs, MemoryDB for Redis, 4 ECS services (deferred), auto-scaling (deferred), IAM roles, CloudWatch alarms |
| **cicd** | Build pipelines | CodeBuild projects (backend), S3 artifacts bucket, IAM roles, CloudWatch logs |

### Feature Flags

| Flag | Layer | Default | Purpose |
|---|---|---|---|
| `enable_frontend` | app | `false` | ALB, frontend SG, ECS task role, frontend log group — no frontend for POC |
| `backend_type` | app | `agentcore` | Backend compute: agentcore / ecs / lambda / none |
| `enable_knowledge_base` | ai | `true` | Bedrock KB + S3 Vectors — no cost concern with S3 Vectors |
| `enable_agent` | ai | `true` | Bedrock Agent with configurable instruction |
| `enable_preprocessor` | ai | `false` | Lambda data preprocessor — waiting for app code |
| `enable_waf` | app | `false` | WAFv2 on ALB — enable for production |
| `enable_messaging` | messaging | `true` | SQS queues (AI + Publisher) with DLQs |
| `enable_memorydb` | messaging | `true` | MemoryDB for Redis cluster |
| `enable_phase2_services` | messaging | `false` | Phase 2 ECS services — waiting for app code |
| `enable_autoscaling` | messaging | `false` | ECS auto-scaling (5x out / 1x in) — enable after services run |

### Backend Type

The app layer supports flexible backend types via `var.backend_type`:

| Type | Description | Phase |
|---|---|---|
| `agentcore` | Amazon Bedrock AgentCore runtime — IAM role + SG only, runtime deployed via CI/CD | 1, 2 |
| `ecs` | Self-managed ECS Fargate service with task definition | 2 (services) |
| `lambda` | Serverless container image (ARM64) | 1 (preprocessor) |
| `none` | No backend compute resources | — |

### Existing S3 Data Buckets (Pre-existing, Not IaC-Managed)

These buckets exist outside the Terraform state and are referenced by IAM policies:

| Bucket | Purpose |
|---|---|
| `linkme-ai-poc-input` | Raw input data (PDFs, images, videos) |
| `linkme-ai-poc-output` | Processed output data |
| `di.research` | Research data |
| `s3-linkme-ai-poc-custom-datasources-us-west-2` | Custom data sources for Knowledge Base |

### Bedrock Model Access

The app layer's IAM policies grant access to:

| Model | Model ID |
|---|---|
| Claude Opus 4.6 | `anthropic.claude-opus-4-6-v1` |
| Claude Sonnet 4.6 | `anthropic.claude-sonnet-4-6` |
| Claude Sonnet 4.5 | `anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5-20251001-v1:0` |
| Amazon Titan Embeddings V2 | `amazon.titan-embed-text-v2:0` |

### Performance & Auto-Scaling

This POC will be performance-tested. Infrastructure must scale quickly and reliably.

- **AI layer services** are inherently serverless (Bedrock, S3 Vectors, Lambda) — auto-scale automatically
- **ECS services** (when enabled) require Application Auto Scaling:
  - **Scale out**: 5x baseline (aggressive — fast cooldown)
  - **Scale in**: 1x baseline (conservative — long cooldown to avoid premature scale-in)

---

## Application Components (Code — TBD)

Application code will be provided separately. Based on the architecture, the expected components are:

### Phase 1

| Component | Runtime | Code Path (expected) | Description |
|---|---|---|---|
| **Bedrock Agent** | AgentCore | `agentcore-be/` | Agent Core configuration: instructions, output schema, tools (web browser), KB integration |
| **Data Preprocessor** | Lambda | TBD | PDF parser, triggered by S3 uploads, routes to Nova Multimodal |

### Phase 2

| Component | Runtime | Code Path (expected) | Description |
|---|---|---|---|
| **AI Message Processor** | ECS / Lambda | TBD | Dequeues from SQS, fetches KB context, calls AI Service, sends DM replies |
| **AI Service** | ECS / AgentCore | TBD | Core intelligence: LLM calls, semantic matching, cross-org KB lookup, rate limit checks |
| **Instagram MockService** | ECS / Lambda | TBD | Simulates Instagram DM API, produces/consumes SQS messages |
| **Publisher MockService** | ECS / Lambda | TBD | Simulates content publishing endpoint |
| **Frontend (Streamlit)** | ECS Fargate | `streamlit-frontend/` | UI for conversation monitoring, KB management (enable via `enable_frontend = true`) |

---

## Open Design Questions

These items are annotated with question marks or "TBD" in the architecture diagrams:

1. **Data Manager into S3?** (Phase 1) — How exactly do vectors and profile documents flow into the KB S3 bucket? Direct write from the agent, or via a dedicated data manager service?
2. **LLM Model TBD** (Phase 2) — Which Bedrock model will the AI Service use for inference? Claude Sonnet 4.6 is likely for cost/speed balance, but benchmarks needed.
3. **Queue for Publisher?** (Phase 2) — Is the publisher queue confirmed? The question mark suggests this integration path may change.
4. **AI Message Processor runtime** — ECS Fargate or Lambda? Depends on message volume and latency requirements.
5. **AI Service runtime** — Standalone ECS service or Bedrock AgentCore? The diagram shows both Bedrock and a separate service box.
6. **Embeddings model alignment** — Phase 1 uses Amazon Nova Embeddings in the diagram, but IaC uses Titan V2. Phase 2 also uses Titan V2. To be unified.
7. **Multi-org MemoryDB topology** — Single cluster with namespace isolation, or separate clusters per org?

---

## Remaining Work (Waiting for App Code)

All infrastructure for both phases is built. The following items activate when application code is provided:

| Item | How to Enable | Layer |
|---|---|---|
| **Lambda data preprocessor** | Set `enable_preprocessor = true`, deploy code | ai |
| **Phase 2 ECS services** (4) | Set `enable_phase2_services = true`, push images to ECR | messaging |
| **ECS auto-scaling** | Set `enable_autoscaling = true` after services are running | messaging |
| **Bedrock Agent action groups** | Define tool schemas in app code, add `aws_bedrockagent_agent_action_group` | ai |
| **Frontend (Streamlit)** | Set `enable_frontend = true`, add frontend ECR repo + CodeBuild | app + cicd |
