# Phase 2 data plane (resources split by purpose):
#   sqs.tf               - incoming (standard) + ai-processing.fifo queues + DLQs
#   dynamodb.tf          - ddb-linkme-ai-poc-results (PK: message_id, GSI1: run_id + processed_at)
#   s3.tf                - linkme-ai-poc-input-messages bucket for simulator input JSONL
#   memorydb.tf          - MemoryDB Redis 7.1+ semantic cache (HNSW 768-dim)
#   security_groups.tf   - MemoryDB SG (workloads layer adds task-ingress rules)
#   cloudwatch.tf        - dash-linkme-ai-poc-simulator + 6 alarms (DLQ, queue age, E2E p95, DDB throttles)
#   iam.tf               - kept minimal (no compute roles; those live in workloads/interactive)
