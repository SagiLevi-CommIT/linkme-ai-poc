locals {
  global_vars  = read_terragrunt_config(find_in_parent_folders("global.hcl")).locals
  account_vars = read_terragrunt_config(find_in_parent_folders("account.hcl")).locals

  env        = "poc"
  env_type   = "poc"
  aws_region = "us-west-2"

  # VPC configuration
  vpc_cidr = "10.143.32.0/20"
  az_count = 2

  # Subnet CIDRs
  subnet_cidr_public_1      = "10.143.32.0/24"
  subnet_cidr_public_2      = "10.143.33.0/24"
  subnet_cidr_private_app_1 = "10.143.34.0/24"
  subnet_cidr_private_app_2 = "10.143.35.0/24"
  subnet_cidr_private_db_1  = "10.143.36.0/24"
  subnet_cidr_private_db_2  = "10.143.37.0/24"

  # CloudWatch log retention (days)
  log_retention_days = 7

  project_name = local.global_vars.project_name

  # ================================================================
  # App layer configuration
  # ================================================================

  # Frontend (ALB, SGs, frontend ECS task role) — false for POC
  enable_frontend = false

  # Backend compute type — POC uses AgentCore Runtime (interactive layer)
  backend_type = "agentcore"

  # Container ports
  app_container_port     = 8501
  backend_container_port = 8080

  # ECR repositories — one per container image that CodeBuild produces
  ecr_repositories = {
    backend         = "Legacy backend image placeholder"
    agentcore       = "AgentCore Runtime image Strands SDK ARM64"
    messages-pusher = "Messages Pusher ECS task image ARM64"
    cache-service   = "Cache Service ECS service image ARM64"
    llm-service     = "LLM Service ECS service image ARM64"
    tei-embedding   = "TEI SageMaker wrapper image for bge-base-en-v1.5"
  }

  # Bedrock foundation model ARNs the backend role may invoke
  # Sonnet 4 5 and Haiku 4 5 are invoked via US CRIS inference profiles — both the
  # profile ARN and the underlying model ARNs are granted.
  bedrock_model_arns = [
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-6-v1",
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
    "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0",
    "arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0",
  ]

  # US Cross-Region Inference profile ARNs (Haiku, Sonnet, Nova)
  bedrock_inference_profile_arns = [
    "arn:aws:bedrock:us-west-2:${local.account_vars.account_id}:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "arn:aws:bedrock:us-west-2:${local.account_vars.account_id}:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "arn:aws:bedrock:us-west-2:${local.account_vars.account_id}:inference-profile/us.amazon.nova-lite-v1:0",
  ]

  # Enable Bedrock Knowledge Base access for backend role
  enable_bedrock_knowledge_base = true

  # WAF on ALB (off for POC)
  enable_waf = false

  # ================================================================
  # AI layer configuration
  # ================================================================

  # Feature flags
  enable_knowledge_base = true
  enable_agent          = true # Preview path Bedrock Agent + alias
  enable_sagemaker      = true # Self-hosted bge-base-en-v1.5 endpoint for semantic cache

  # Bedrock Agent (preview path only; Phase 1 conversational uses AgentCore in interactive layer)
  agent_foundation_model = "anthropic.claude-sonnet-4-6"
  agent_instruction      = "You are the preview assistant for the LinkMe AI POC. Use the attached creator profile and the tenant-filtered Bedrock Knowledge Base retrieval to answer preview questions. Keep answers faithful to the creator voice and never hallucinate facts."

  # Bedrock Knowledge Base — embedding model + vector config (Titan V2 1024-dim)
  embedding_model_arn = "arn:aws:bedrock:us-west-2::foundation-model/amazon.titan-embed-text-v2:0"
  vector_dimension    = 1024

  # SageMaker embedding endpoint config (bge-base-en-v1.5 at 768-dim)
  # Two configs live under this endpoint:
  #   - default: ml.t2.medium x1 (idle POC baseline, ~$41/mo)
  #   - burst:   ml.c6i.large x2, autoscaling to x8 (spec burst config)
  # Operator flips between them via aws sagemaker update-endpoint --endpoint-config-name.
  # Burst v13 (2026-04-20) proved cache-service is the 974 msg/s ceiling,
  # not the GPU — T4 delivers the same throughput as A10G for this workload
  # and saves $644/mo vs ml.g5.xlarge.
  # Names below match the actually-deployed resources (created via CLI
  # during perf tuning, adopted into TF state via `import` blocks in
  # layers/ai/sagemaker.tf).
  sagemaker_embedding = {
    endpoint_name     = "linkme-poc-embedding"
    model_name        = "linkme-poc-embedding-tei-t4"
    config_name       = "linkme-poc-embedding-tei-g4dnx1"
    instance_type     = "ml.g4dn.xlarge"
    initial_count     = 1
    huggingface_model = "BAAI/bge-base-en-v1.5"
    embedding_dim     = 768
    # Pinned TEI wrapper image tag in the tei-embedding ECR repo.
    # Produced by the tei-embedding CodeBuild project; bump to roll
    # the SageMaker endpoint onto a newer image.
    image_tag                                   = "turing-1.6-sm-85cd7334e5d5"
    # Cache-service at current scale (6 tasks x 6 workers = 36 embeds/s) only
    # uses ~60% of one T4; scaling SM to 2 produced identical throughput
    # across burst v13-v15. Pinned to 1 instance until cache-service grows
    # past that ceiling.
    enable_autoscaling                          = true
    autoscaling_min                             = 1
    autoscaling_max                             = 1
    autoscaling_target_invocations_per_instance = 500
  }

  # ================================================================
  # Messaging layer configuration (Phase 2 data plane)
  # ================================================================

  # Feature flags
  enable_messaging = true
  enable_memorydb  = true

  # SQS config (incoming standard + ai-processing.fifo)
  sqs_config = {
    message_retention_seconds        = 345600 # 4 days
    dlq_max_receive_count            = 5
    incoming_visibility_timeout      = 120
    ai_processing_visibility_timeout = 900
  }

  # MemoryDB config — Redis 7.1+ with HNSW parameter group for 768-dim semantic cache
  memorydb_config = {
    node_type                = "db.t4g.small" # right-sized for POC idle; can bump to t4g.medium for heavy burst campaigns
    engine_version           = "7.1"
    num_shards               = 1
    num_replicas_per_shard   = 0
    port                     = 6379
    snapshot_retention_limit = 1
    maintenance_window       = "sun:08:00-sun:09:00"
    parameter_group_family   = "memorydb_redis7"
  }

  # DDB Results table
  ddb_results_config = {
    table_name = "ddb-linkme-ai-poc-results"
    gsi_name   = "run-id-processed-at"
    ttl_attr   = "expires_at"
  }

  # S3 input-messages bucket (Phase 2 simulator input)
  s3_input_messages_bucket = "linkme-ai-poc-input-messages"

  # CloudWatch dashboard name
  simulator_dashboard_name = "dash-linkme-ai-poc-simulator"

  # ================================================================
  # Interactive layer configuration (Phase 1 interactive flow)
  # ================================================================

  enable_interactive       = true
  enable_api_lambda        = true
  enable_preprocessor      = true
  enable_agentcore_runtime = true
  enable_ui_bucket         = true

  # API Lambda (slim REST surface with Function URL)
  api_lambda_config = {
    function_name = "linkme-poc-api"
    runtime       = "python3.12"
    memory_mb     = 512
    timeout_s     = 30
    package_path  = "../../../../../../src/api" # relative to layer dir
    handler       = "app.handler"
  }

  # Preprocessing Lambda (S3-event-driven; Nova Lite for multimodal)
  preprocessor_lambda_config = {
    function_name = "linkme-poc-preprocessing"
    runtime       = "python3.12"
    memory_mb     = 1024
    timeout_s     = 300
    package_path  = "../../../../../../src/preprocessing"
    handler       = "handler.lambda_handler"
  }

  # AgentCore Runtime (Strands SDK container, Phase 1 conversational)
  # AgentCore runtime names must match ^[a-zA-Z][a-zA-Z0-9_]{0,47}$ (no hyphens; underscores only)
  agentcore_runtime_config = {
    runtime_name = "agentcore_linkme_ai_poc_phase1"
    endpoint_id  = "DEFAULT"
    network_mode = "PUBLIC" # POC — flip to VPC for production
    ecr_repo_key = "agentcore"
  }

  # UI static site bucket
  ui_bucket_name = "linkme-poc-ui"

  # DynamoDB tables (Phase 1 interactive store)
  ddb_tables = {
    profiles = {
      name         = "ddb-linkme-poc-profiles"
      hash_key     = "tenant_id"
      billing_mode = "PAY_PER_REQUEST"
    }
    cache = {
      name         = "ddb-linkme-poc-cache"
      hash_key     = "pk"
      billing_mode = "PAY_PER_REQUEST"
    }
    messages = {
      name         = "ddb-linkme-poc-messages"
      hash_key     = "message_id"
      billing_mode = "PAY_PER_REQUEST"
    }
    semantic_cache = {
      name         = "ddb-linkme-poc-semantic-cache"
      hash_key     = "pk"
      billing_mode = "PAY_PER_REQUEST"
    }
  }

  # ================================================================
  # Workloads layer configuration (Phase 2 compute)
  # ================================================================

  enable_workloads   = true
  enable_autoscaling = true

  # Fargate tasks (ARM64 Graviton)
  # desired_count is set at apply time; operator scales via `aws ecs update-service` for burst runs.
  # min/max_capacity bound the autoscaling range — widened for the 500K spec burst.
  workloads_task_config = {
    cache_service = {
      name         = "cache-service"
      ecr_repo_key = "cache-service"
      cpu          = 1024
      memory       = 2048
      # Sized so max_capacity tasks x worker_count stays below the SageMaker
      # burst ceiling that triggers autoscale-out (target=500 invocations per
      # instance per minute). 6 tasks x 6 workers = 36 concurrent embeds.
      desired_count   = 2
      min_capacity    = 2
      max_capacity    = 6
      worker_count    = 6
      sqs_target_msgs = 1000
    }
    llm_service = {
      name            = "llm-service"
      ecr_repo_key    = "llm-service"
      cpu             = 1024
      memory          = 2048
      desired_count   = 2
      min_capacity    = 2
      max_capacity    = 4
      sqs_target_msgs = 50
    }
    messages_pusher = {
      name         = "messages-pusher"
      ecr_repo_key = "messages-pusher"
      cpu          = 512
      memory       = 1024
      # No service — operator-triggered run-task only
    }
  }

  # ================================================================
  # CICD layer configuration
  # ================================================================

  codecommit_repo_name = "linkme-ai-poc"
  codebuild_source_ref = "refs/heads/main"

  # CodeBuild projects — one per container image
  codebuild_projects = {
    backend = {
      description      = "Reserved legacy backend image"
      buildspec        = "buildspec.yml"
      compute_type     = "BUILD_GENERAL1_LARGE"
      environment_type = "ARM_CONTAINER"
      image            = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
      ecr_repo_key     = "backend"
      privileged_mode  = true
    }
    agentcore = {
      description      = "Build AgentCore Runtime ARM64 container Strands SDK"
      buildspec        = "buildspec.yml"
      compute_type     = "BUILD_GENERAL1_LARGE"
      environment_type = "ARM_CONTAINER"
      image            = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
      ecr_repo_key     = "agentcore"
      privileged_mode  = true
    }
    messages-pusher = {
      description      = "Build Messages Pusher ECS task ARM64 container"
      buildspec        = "src/messages_pusher/buildspec.yml"
      compute_type     = "BUILD_GENERAL1_LARGE"
      environment_type = "ARM_CONTAINER"
      image            = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
      ecr_repo_key     = "messages-pusher"
      privileged_mode  = true
    }
    cache-service = {
      description      = "Build Cache Service ECS service ARM64 container"
      buildspec        = "src/cache_service/buildspec.yml"
      compute_type     = "BUILD_GENERAL1_LARGE"
      environment_type = "ARM_CONTAINER"
      image            = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
      ecr_repo_key     = "cache-service"
      privileged_mode  = true
    }
    llm-service = {
      description      = "Build LLM Service ECS service ARM64 container"
      buildspec        = "src/llm_service/buildspec.yml"
      compute_type     = "BUILD_GENERAL1_LARGE"
      environment_type = "ARM_CONTAINER"
      image            = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
      ecr_repo_key     = "llm-service"
      privileged_mode  = true
    }
    # TEI runs on a SageMaker GPU endpoint, not ECS, so this is x86_64
    # and has no post-build deploy step in its buildspec (operator bumps
    # sagemaker_embedding.image_tag in region.hcl to roll the endpoint).
    tei-embedding = {
      description      = "Build TEI SageMaker wrapper image for bge-base-en-v1.5"
      buildspec        = "src/tei_embedding/buildspec.yml"
      compute_type     = "BUILD_GENERAL1_LARGE"
      environment_type = "LINUX_CONTAINER"
      image            = "aws/codebuild/amazonlinux2-x86_64-standard:5.0"
      ecr_repo_key     = "tei-embedding"
      privileged_mode  = true
    }
  }
}
