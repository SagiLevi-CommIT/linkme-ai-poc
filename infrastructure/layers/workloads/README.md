# workloads

Phase 2 pipeline compute for the LinkMe AI POC simulator.

## Contents

| Resource | Purpose |
|---|---|
| `aws_ecs_task_definition.cache_service` | Consumes SQS incoming, exact/semantic cache lookup, hit → DDB results, miss → SQS ai-processing.fifo |
| `aws_ecs_task_definition.llm_service` | Consumes SQS ai-processing.fifo, profile + KB retrieve + Bedrock invoke, writes DDB results + cache writeback |
| `aws_ecs_task_definition.messages_pusher` | Operator-triggered `aws ecs run-task` driver — reads S3 JSONL batches, fans out to SQS incoming via `SendMessageBatch` |
| `aws_ecs_service.cache_service` + `.llm_service` | Long-running Fargate ARM64 services; `messages_pusher` has NO service (task-only) |
| `aws_appautoscaling_target` + `..._policy.*_sqs_depth` | Target-tracking on SQS `ApproximateNumberOfMessagesVisible` — 1000 msgs/task for cache, 50 msgs/task for llm |
| `aws_iam_role.task["..."]` | Per-service task roles: cache-service (SQS + SageMaker + DDB), llm-service (SQS + Bedrock + SageMaker + KB + DDB), messages-pusher (S3 + SQS) |
| `aws_security_group.task` | Shared task ENI SG with all-egress |
| `aws_vpc_security_group_ingress_rule.memorydb_from_tasks` | Adds ingress to messaging-layer MemoryDB SG from the task SG |

## Dependencies

- `vpc` — private subnets + CIDR
- `app` — ECS cluster + task execution role + ECR repos (cache-service, llm-service, messages-pusher)
- `ai` — SageMaker embedding endpoint + Knowledge Base ID
- `messaging` — SQS queues, DDB results table, S3 input-messages bucket, MemoryDB endpoint + SG

## Feature flags

| Flag | Default | Effect |
|---|---|---|
| `enable_workloads` | true | Create task defs + services + IAM + SG |
| `enable_autoscaling` | true | Create App Auto Scaling targets + target-tracking policies |

## Burst tuning (operator, per simulation run)

Edit `workloads_task_config` in `region.hcl` before a burst run:

```hcl
cache_service.max_capacity   = 15
cache_service.desired_count  = 10
llm_service.max_capacity     = 10
llm_service.desired_count    = 6
```

`terragrunt apply`, run the simulation, then revert these values.
