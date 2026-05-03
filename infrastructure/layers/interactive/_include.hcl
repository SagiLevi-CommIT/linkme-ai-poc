terraform {
  source = "${get_repo_root()}/infrastructure/layers/interactive//"
}

locals {
  region_vars = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals
}

dependency "app" {
  config_path = "../app"

  mock_outputs = {
    ecr_repository_uris = {
      agentcore = "000000000000.dkr.ecr.us-west-2.amazonaws.com/mock-agentcore"
    }
    ecs_task_execution_role_arn = "arn:aws:iam::000000000000:role/mock-ecs-execution-role"
    kms_cloudwatch_key_arn      = "arn:aws:kms:us-west-2:000000000000:key/00000000-0000-0000-0000-000000000000"
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

dependency "ai" {
  config_path = "../ai"

  mock_outputs = {
    knowledge_base_id        = "MOCKKB0001"
    kb_source_bucket_name    = "mock-linkme-poc-kb-source"
    raw_uploads_bucket_name  = "mock-linkme-poc-raw-uploads"
    raw_uploads_bucket_arn   = "arn:aws:s3:::mock-linkme-poc-raw-uploads"
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

dependency "messaging" {
  config_path = "../messaging"

  mock_outputs = {
    incoming_queue_url = "https://sqs.us-west-2.amazonaws.com/000000000000/mock-incoming"
    incoming_queue_arn = "arn:aws:sqs:us-west-2:000000000000:mock-incoming"
    results_table_name = "ddb-linkme-ai-poc-results"
    results_table_arn  = "arn:aws:dynamodb:us-west-2:000000000000:table/ddb-linkme-ai-poc-results"
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

inputs = {
  region = local.region_vars.aws_region

  agentcore_ecr_repository_url = dependency.app.outputs.ecr_repository_uris[local.region_vars.agentcore_runtime_config.ecr_repo_key]
  cloudwatch_kms_key_arn       = try(dependency.app.outputs.kms_cloudwatch_key_arn, null)

  knowledge_base_id       = dependency.ai.outputs.knowledge_base_id
  kb_source_bucket_name   = dependency.ai.outputs.kb_source_bucket_name
  raw_uploads_bucket_name = dependency.ai.outputs.raw_uploads_bucket_name
  raw_uploads_bucket_arn  = dependency.ai.outputs.raw_uploads_bucket_arn

  incoming_queue_url = dependency.messaging.outputs.incoming_queue_url
  incoming_queue_arn = dependency.messaging.outputs.incoming_queue_arn
  results_table_name = dependency.messaging.outputs.results_table_name
  results_table_arn  = dependency.messaging.outputs.results_table_arn

  # Resolve Lambda package paths to absolute filesystem paths at plan time,
  # so archive_file.source_dir works regardless of the terragrunt-cache layout.
  # Each Lambda zips the whole src/ tree so shared libs (common, batch_llm,
  # cache_processor) are importable — handler paths are adjusted accordingly.
  api_lambda_config = merge(
    local.region_vars.api_lambda_config,
    {
      package_path = "${get_repo_root()}/src"
      handler      = "api.app.handler"
    }
  )
  preprocessor_lambda_config = merge(
    local.region_vars.preprocessor_lambda_config,
    {
      package_path = "${get_repo_root()}/src"
      handler      = "preprocessing.handler.lambda_handler"
    }
  )
}
