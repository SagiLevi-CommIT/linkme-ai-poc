# Terragrunt Stack Documentation

## Project Overview

| Setting | Value |
|---|---|
| Project Name | `linkme-ai` |
| AWS Account | `commit-ai-sandbox-01` (`095128162384`) |
| Region | `us-west-2` |
| Environment | `poc` |
| Total Units | 5 |
| Terraform | `>= 1.13.0, < 2.0.0` |
| Terragrunt | `>= 0.90.0, < 1.0.0` |
| AWS Provider | `~> 6.0` |

---

## Dependency Graph

```
.
╰── vpc
    ├── ai
    ├── app
    │   ├── cicd
    │   ╰── messaging
    ├── cicd
    ╰── messaging
```

**Apply order:** `vpc` → `app` + `ai` (parallel) → `messaging` + `cicd` (parallel)

**Destroy order:** `messaging` + `cicd` → `app` + `ai` → `vpc`

---

## Unit Summary

| Unit | Layer Source | Dependencies | Key Resources | Feature Flags |
|---|---|---|---|---|
| **vpc** | `layers/vpc` | none | VPC, subnets, NAT, IGW, VPC endpoints, flow logs | — |
| **app** | `layers/app` | vpc | ECR repos, ECS cluster, KMS, IAM roles, SGs | `enable_frontend`, `backend_type` |
| **ai** | `layers/ai` | vpc | Bedrock KB, S3 Vectors, Bedrock Agent, Lambda | `enable_knowledge_base`, `enable_agent`, `enable_preprocessor` |
| **messaging** | `layers/messaging` | vpc, app | SQS queues, MemoryDB, ECS services, auto-scaling | `enable_messaging`, `enable_memorydb`, `enable_phase2_services`, `enable_autoscaling` |
| **cicd** | `layers/cicd` | vpc, app | CodeBuild projects, S3 artifacts | — |

---

## Hierarchy Variable Documentation

### `global.hcl` — Cross-account settings

| Variable | Value | Description |
|---|---|---|
| `project_name` | `linkme-ai` | Used in all resource naming via `name_fmt` |
| `commit_ai_sandbox_01_account_id` | `095128162384` | AWS account ID |
| `account_ids` | map | Account name → ID mapping |

### `account.hcl` — Account-level settings

| Variable | Value | Description |
|---|---|---|
| `account_id` | `095128162384` | Derived from `global.hcl` |

### `region.hcl` — Region and deployment configuration

| Section | Variables |
|---|---|
| **Environment** | `env = "poc"`, `env_type = "poc"`, `aws_region = "us-west-2"` |
| **VPC** | `vpc_cidr`, `az_count = 2`, 6 subnet CIDRs |
| **App layer** | `enable_frontend`, `backend_type`, `ecr_repositories`, `s3_data_buckets`, `bedrock_model_arns`, `enable_bedrock_knowledge_base`, `enable_waf` |
| **AI layer** | `enable_knowledge_base`, `enable_agent`, `enable_preprocessor`, `agent_foundation_model`, `agent_instruction`, `embedding_model_arn`, `vector_dimension` |
| **Messaging layer** | `enable_messaging`, `enable_memorydb`, `enable_phase2_services`, `enable_autoscaling` |
| **CICD layer** | `codecommit_repo_name`, `codebuild_projects` |

---

## Root Configuration (`terragrunt_base.hcl`)

### Remote State

```
Backend:  S3
Bucket:   terraform-states-<account_id>-<region>
Key:      <account>/<region>/<unit>/terraform.tfstate
Encrypt:  true
Locking:  native S3 (use_lockfile = true)
```

### Generated Files

| File | Purpose |
|---|---|
| `_backend.tf` | S3 backend configuration — auto-generated on every `init` |

### Hooks

| Hook | Trigger | Script |
|---|---|---|
| `ensure_state_bucket` | `init` | `scripts/ensure-state-bucket.sh` — idempotently creates S3 state bucket |
| `tflint` | `plan`, `apply` | `scripts/tflint-hook.sh` — runs tflint validation |

### Default Tags (auto-applied via `TF_AWS_DEFAULT_TAGS_*` env vars)

| Tag | Source |
|---|---|
| `environment-name` | `region.hcl` → `env` |
| `environment-type` | `region.hcl` → `env_type` |
| `created-by` | `terraform` |
| `managed-by` | `terraform` |
| `layer` | Derived from unit directory name |

### AWS Provider Configuration

| Setting | Value |
|---|---|
| `AWS_PROFILE` | Derived from account folder name (`commit-ai-sandbox-01`) |
| `AWS_REGION` | From `region.hcl` → `aws_region` |

### Input Merge Strategy

Inputs are merged from three hierarchy levels:
```
global.hcl + account.hcl + region.hcl → merged into Terraform inputs
```
Layer-specific inputs from `_include.hcl` override or supplement the hierarchy merge.

---

## Per-Unit Details

### vpc

| | |
|---|---|
| **Source** | `layers/vpc` |
| **Dependencies** | none |
| **Inputs from hierarchy** | `account_id`, `env`, `env_type`, `project_name`, `vpc_cidr`, `az_count`, subnet CIDRs, `log_retention_days` |
| **Inputs from `_include.hcl`** | `region` |
| **Key outputs** | `vpc_id`, `vpc_cidr`, `public_subnet_*_id`, `private_app_subnet_*_id`, `private_db_subnet_*_id`, `nat_gateway_id` |

### app

| | |
|---|---|
| **Source** | `layers/app` |
| **Dependencies** | `vpc` |
| **Inputs from vpc** | `vpc_id`, `public_subnet_1_id`, `public_subnet_2_id`, `private_app_subnet_ids` |
| **Inputs from `_include.hcl`** | `region` |
| **Key outputs** | `ecs_cluster_arn`, `ecs_cluster_name`, `ecs_task_execution_role_arn`, `ecr_repository_uris`, `ecr_repository_arns`, `backend_role_arn`, `backend_security_group_id` |

### ai

| | |
|---|---|
| **Source** | `layers/ai` |
| **Dependencies** | `vpc` |
| **Inputs from vpc** | `vpc_id`, `private_app_subnet_ids` |
| **Inputs from `_include.hcl`** | `region` |
| **Key outputs** | `knowledge_base_id`, `knowledge_base_arn`, `agent_id`, `agent_alias_id`, `kb_data_bucket_name`, `vector_bucket_name` |

### messaging

| | |
|---|---|
| **Source** | `layers/messaging` |
| **Dependencies** | `vpc`, `app` |
| **Inputs from vpc** | `vpc_id`, `private_app_subnet_ids`, `private_db_subnet_ids` |
| **Inputs from app** | `ecs_cluster_arn`, `ecs_task_execution_role_arn`, `ecr_repository_uris` |
| **Inputs from `_include.hcl`** | `region` |
| **Key outputs** | `sqs_ai_queue_url`, `sqs_publisher_queue_url`, `memorydb_cluster_endpoint`, service names and role ARNs |

### cicd

| | |
|---|---|
| **Source** | `layers/cicd` |
| **Dependencies** | `vpc`, `app` |
| **Inputs from vpc** | `private_app_subnet_*_id` |
| **Inputs from app** | `ecr_repository_arns`, `ecr_repository_uris`, `ecs_cluster_name`, `ecs_security_group_id`, `ecs_task_execution_role_arn`, `ecs_task_role_arn`, `backend_role_arn`, `backend_security_group_id`, `frontend_target_group_arn` |
| **Inputs from `_include.hcl`** | `region`, `codebuild_pass_role_arns`, `codebuild_extra_env_vars`, `codebuild_extra_iam_policies` |
| **Key outputs** | `artifacts_bucket_name`, `codebuild_project_names`, `codebuild_role_arns` |

---

## Quick Reference

```bash
# Navigate to the stack root
cd infrastructure/accounts/commit-ai-sandbox-01/us-west-2

# Validate all units
terragrunt run --all validate

# Plan all units in DAG order
terragrunt run --all plan

# Apply all units in DAG order
terragrunt run --all apply

# Apply a single unit
cd messaging && terragrunt apply

# Destroy in reverse DAG order
terragrunt run --all destroy

# View the dependency graph
terragrunt list --dag --tree

# List all units
terragrunt find
```
