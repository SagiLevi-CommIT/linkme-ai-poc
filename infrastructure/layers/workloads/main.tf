# Phase 2 workloads layer - resources split by purpose:
#   task_definitions.tf - 3 ECS Fargate ARM64 task definitions + log groups
#   services.tf         - cache-service + llm-service long-running ECS services
#   autoscaling.tf      - Application Auto Scaling on SQS depth (cache + llm)
#   iam.tf              - per-service task roles (cache, llm, messages-pusher)
#   security_groups.tf  - task ENI SG + MemoryDB ingress rule
