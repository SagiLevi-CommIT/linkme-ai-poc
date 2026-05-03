# Infrastructure

Terraform/Terragrunt infrastructure-as-code for the LinkMe AI AgentCore POC.
Replaces the original CloudFormation stacks (`vpc-stack.yaml`, `app-stack.yaml`, `cicd-stack.yaml`).

## Structure

```
infrastructure/
  accounts/                                  # Terragrunt hierarchy
    global.hcl                               # Project name, account IDs
    terragrunt_base.hcl                      # Remote state, version constraints, tflint hook, default tags
    commit-ai-sandbox-01/
      account.hcl                            # account_id = 095128162384
      us-west-2/
        region.hcl                           # env, region, VPC/subnet CIDRs, S3 bucket names
        vpc/terragrunt.hcl                   # Unit: VPC layer
        app/terragrunt.hcl                   # Unit: App layer
        ai/terragrunt.hcl                    # Unit: AI layer
        messaging/terragrunt.hcl             # Unit: Messaging layer
        cicd/terragrunt.hcl                  # Unit: CI/CD layer
  layers/                                    # Terraform root modules
    vpc/                                     # VPC, subnets, NAT, routing, flow logs, VPC endpoints
    app/                                     # ECR, SGs, IAM, ALB, ECS cluster
    ai/                                      # Bedrock KB, Agent, S3 Vectors, Lambda preprocessor
    messaging/                               # SQS queues, MemoryDB, Phase 2 ECS services, auto-scaling
    cicd/                                    # CodeBuild projects, S3 artifacts, IAM
  scripts/
    tflint-hook.sh                           # tflint before-hook (runs on plan/apply)
  .tflint.hcl                               # tflint config (disables terraform_required_version)
```

## Dependency graph

```
vpc  (no deps)
 ├─► app       (depends on vpc)
 │    ├─► cicd      (depends on app + vpc)
 │    └─► messaging (depends on app + vpc)
 └─► ai        (depends on vpc)
```

## Layers

| Layer | README | Resources |
|---|---|---|
| `layers/vpc` | [vpc/README.md](layers/vpc/README.md) | VPC, subnets, NAT Gateway, route tables, VPC flow logs |
| `layers/app` | [app/README.md](layers/app/README.md) | ECR, KMS, security groups, IAM roles, ALB, ECS cluster, CloudWatch |
| `layers/ai` | [ai/README.md](layers/ai/README.md) | Bedrock KB, S3 Vectors, Bedrock Agent, Lambda preprocessor, IAM |
| `layers/messaging` | [messaging/README.md](layers/messaging/README.md) | SQS queues, MemoryDB, Phase 2 ECS services, auto-scaling, CloudWatch |
| `layers/cicd` | [cicd/README.md](layers/cicd/README.md) | CodeBuild projects, S3 artifacts bucket, IAM roles, CloudWatch |

## Remote state

S3 bucket: `terraform-states-095128162384-us-west-2`
- Encrypted (AES256), versioned, public access blocked
- State key pattern: `<account>/<region>/<unit>/terraform.tfstate`
- Native S3 locking (`use_lockfile = true`)

## Quick start

```bash
# Prerequisites: AWS SSO authenticated as commit-ai-sandbox-01 profile, terragrunt >= v0.90

cd infrastructure/accounts/commit-ai-sandbox-01/us-west-2

# Validate all units (uses mock outputs for dependencies)
terragrunt run --all validate

# Plan all units in dependency order
terragrunt run --all plan

# Apply all units in dependency order (vpc → app/ai → messaging/cicd)
terragrunt run --all apply
```

## Environment variables (region.hcl)

| Variable | Value | Description |
|---|---|---|
| `env` | `poc` | Environment name |
| `env_type` | `nonprod` | Environment type |
| `aws_region` | `us-west-2` | AWS region |
| `vpc_cidr` | `10.142.16.0/20` | VPC CIDR |
| `az1` / `az2` | `us-west-2a` / `us-west-2b` | Availability zones |
| `project_name` | `linkme-ai` | Project name (from global.hcl) |
| `s3_input_bucket` | `linkme-ai-poc-input` | Pre-existing input data bucket |
| `s3_output_bucket` | `linkme-ai-poc-output` | Pre-existing output data bucket |
| `s3_research_bucket` | `di.research` | Pre-existing research data bucket |
