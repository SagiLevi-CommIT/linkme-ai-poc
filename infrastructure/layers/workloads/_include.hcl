terraform {
  source = "${get_repo_root()}/infrastructure/layers/workloads//"
}

locals {
  region_vars = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals
}

dependency "vpc" {
  config_path = "../vpc"

  mock_outputs = {
    vpc_id                 = "vpc-00000000000000000"
    private_app_subnet_ids = ["subnet-00000000000000000", "subnet-00000000000000001"]
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

dependency "app" {
  config_path = "../app"

  mock_outputs = {
    ecs_cluster_arn             = "arn:aws:ecs:us-west-2:000000000000:cluster/mock-cluster"
    ecs_cluster_name            = "mock-cluster"
    ecs_task_execution_role_arn = "arn:aws:iam::000000000000:role/mock-ecs-execution-role"
    ecr_repository_uris = {
      cache-service   = "000000000000.dkr.ecr.us-west-2.amazonaws.com/mock-cache"
      llm-service     = "000000000000.dkr.ecr.us-west-2.amazonaws.com/mock-llm"
      messages-pusher = "000000000000.dkr.ecr.us-west-2.amazonaws.com/mock-pusher"
    }
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

dependency "ai" {
  config_path = "../ai"

  mock_outputs = {
    knowledge_base_id         = "MOCKKB0001"
    sagemaker_endpoint_name   = "linkme-poc-embedding"
    sagemaker_endpoint_arn    = "arn:aws:sagemaker:us-west-2:000000000000:endpoint/linkme-poc-embedding"
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

dependency "interactive" {
  config_path = "../interactive"

  mock_outputs = {
    ddb_table_arns = {
      profiles       = "arn:aws:dynamodb:us-west-2:000000000000:table/mock-profiles"
      cache          = "arn:aws:dynamodb:us-west-2:000000000000:table/mock-cache"
      messages       = "arn:aws:dynamodb:us-west-2:000000000000:table/mock-messages"
      semantic_cache = "arn:aws:dynamodb:us-west-2:000000000000:table/mock-semantic-cache"
    }
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

dependency "messaging" {
  config_path = "../messaging"

  mock_outputs = {
    incoming_queue_url       = "https://sqs.us-west-2.amazonaws.com/000000000000/mock-incoming"
    incoming_queue_arn       = "arn:aws:sqs:us-west-2:000000000000:mock-incoming"
    ai_processing_queue_url  = "https://sqs.us-west-2.amazonaws.com/000000000000/mock-ai.fifo"
    ai_processing_queue_arn  = "arn:aws:sqs:us-west-2:000000000000:mock-ai.fifo"
    results_table_name       = "ddb-linkme-ai-poc-results"
    results_table_arn        = "arn:aws:dynamodb:us-west-2:000000000000:table/ddb-linkme-ai-poc-results"
    input_messages_bucket    = "linkme-ai-poc-input-messages"
    input_messages_bucket_arn = "arn:aws:s3:::linkme-ai-poc-input-messages"
    message_lifecycle_log_group_arn = "arn:aws:logs:us-west-2:000000000000:log-group:/linkme/poc/message-lifecycle"
    message_lifecycle_log_group_name = "/linkme/poc/message-lifecycle"
    poc_metrics_namespace = "Linkme/PoC"
    memorydb_endpoint        = "mock.example.com"
    memorydb_port            = 6379
    memorydb_security_group_id = "sg-00000000000000000"
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

inputs = {
  region = local.region_vars.aws_region

  vpc_id                 = dependency.vpc.outputs.vpc_id
  private_app_subnet_ids = dependency.vpc.outputs.private_app_subnet_ids

  ecs_cluster_arn             = dependency.app.outputs.ecs_cluster_arn
  ecs_cluster_name            = dependency.app.outputs.ecs_cluster_name
  ecs_task_execution_role_arn = dependency.app.outputs.ecs_task_execution_role_arn
  ecr_repository_uris         = dependency.app.outputs.ecr_repository_uris

  knowledge_base_id             = "4OCVLZA0SR"
  knowledge_base_data_source_id = "XUUR927HC8"
  sagemaker_endpoint_name = dependency.ai.outputs.sagemaker_endpoint_name
  sagemaker_endpoint_arn  = dependency.ai.outputs.sagemaker_endpoint_arn

  incoming_queue_url         = dependency.messaging.outputs.incoming_queue_url
  incoming_queue_arn         = dependency.messaging.outputs.incoming_queue_arn
  ai_processing_queue_url    = dependency.messaging.outputs.ai_processing_queue_url
  ai_processing_queue_arn    = dependency.messaging.outputs.ai_processing_queue_arn
  results_table_name         = dependency.messaging.outputs.results_table_name
  results_table_arn          = dependency.messaging.outputs.results_table_arn
  input_messages_bucket      = dependency.messaging.outputs.input_messages_bucket
  input_messages_bucket_arn  = dependency.messaging.outputs.input_messages_bucket_arn
  message_lifecycle_log_group_arn  = dependency.messaging.outputs.message_lifecycle_log_group_arn
  message_lifecycle_log_group_name = dependency.messaging.outputs.message_lifecycle_log_group_name
  poc_metrics_namespace            = dependency.messaging.outputs.poc_metrics_namespace
  memorydb_endpoint          = dependency.messaging.outputs.memorydb_endpoint
  memorydb_port              = dependency.messaging.outputs.memorydb_port
  memorydb_security_group_id = dependency.messaging.outputs.memorydb_security_group_id

  phase1_ddb_table_arns = values(dependency.interactive.outputs.ddb_table_arns)
}
