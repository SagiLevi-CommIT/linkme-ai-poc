# Phase 1 interactive layer - resources split by purpose:
#   dynamodb.tf       - profiles, cache, messages, semantic-cache tables
#   api.tf            - API Lambda + Function URL + IAM + log group
#   preprocessing.tf  - Preprocessing Lambda + S3 event notification on raw-uploads
#   agentcore.tf      - AgentCore Runtime (Strands SDK ARM64) + IAM
#   ui.tf             - UI static S3 bucket + website
#   iam.tf            - shared lambda assume-role policy doc
