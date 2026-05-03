# Resources in this layer are split by purpose:
#   s3.tf             - kb-source + raw-uploads buckets
#   vectors.tf        - S3 Vectors bucket + index (conditional: enable_knowledge_base)
#   knowledge_base.tf - Bedrock KB + S3 data source (conditional: enable_knowledge_base)
#   agent.tf          - Bedrock Agent + alias + KB association (preview path, conditional: enable_agent)
#   sagemaker.tf      - SageMaker model + endpoint_config + endpoint (bge-base-en-v1.5, 768-dim)
#   iam.tf            - IAM roles for KB and Agent
