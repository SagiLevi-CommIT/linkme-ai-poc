terraform {
  source = "${get_repo_root()}/infrastructure/layers/cicd//"
}

locals {
  region_vars = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals
}

dependency "vpc" {
  config_path = "../vpc"

  mock_outputs = {
    private_app_subnet_ids = ["subnet-00000000000000000", "subnet-00000000000000001"]
    vpc_id                 = "vpc-00000000000000000"
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

dependency "app" {
  config_path = "../app"

  mock_outputs = {
    ecr_repository_arns = {
      backend         = "arn:aws:ecr:us-west-2:000000000000:repository/mock-backend"
      agentcore       = "arn:aws:ecr:us-west-2:000000000000:repository/mock-agentcore"
      messages-pusher = "arn:aws:ecr:us-west-2:000000000000:repository/mock-pusher"
      cache-service   = "arn:aws:ecr:us-west-2:000000000000:repository/mock-cache"
      llm-service     = "arn:aws:ecr:us-west-2:000000000000:repository/mock-llm"
    }
    ecr_repository_uris = {
      backend         = "000000000000.dkr.ecr.us-west-2.amazonaws.com/mock-backend"
      agentcore       = "000000000000.dkr.ecr.us-west-2.amazonaws.com/mock-agentcore"
      messages-pusher = "000000000000.dkr.ecr.us-west-2.amazonaws.com/mock-pusher"
      cache-service   = "000000000000.dkr.ecr.us-west-2.amazonaws.com/mock-cache"
      llm-service     = "000000000000.dkr.ecr.us-west-2.amazonaws.com/mock-llm"
    }
    ecs_cluster_name            = "mock-cluster"
    ecs_task_execution_role_arn = "arn:aws:iam::000000000000:role/mock-ecs-execution-role"
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

dependency "interactive" {
  config_path = "../interactive"

  mock_outputs = {
    agentcore_runtime_id       = "MOCKRUNTIME"
    agentcore_runtime_role_arn = "arn:aws:iam::000000000000:role/mock-agentcore"
    api_function_name          = "linkme-poc-api"
    preprocessor_function_name = "linkme-poc-preprocessing"
    ddb_table_names = {
      profiles       = "mock-ddb-profiles"
      cache          = "mock-ddb-cache"
      messages       = "mock-ddb-messages"
      semantic_cache = "mock-ddb-semantic-cache"
    }
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

dependency "workloads" {
  config_path = "../workloads"

  mock_outputs = {
    cache_service_name                  = "mock-cache"
    cache_service_task_definition_arn   = "arn:aws:ecs:us-west-2:000000000000:task-definition/mock-cache:1"
    llm_service_name                    = "mock-llm"
    llm_service_task_definition_arn     = "arn:aws:ecs:us-west-2:000000000000:task-definition/mock-llm:1"
    messages_pusher_task_definition_arn = "arn:aws:ecs:us-west-2:000000000000:task-definition/mock-pusher:1"
    task_role_arns = {
      cache_service   = "arn:aws:iam::000000000000:role/mock-cache-role"
      llm_service     = "arn:aws:iam::000000000000:role/mock-llm-role"
      messages_pusher = "arn:aws:iam::000000000000:role/mock-pusher-role"
    }
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

inputs = {
  region              = local.region_vars.aws_region
  ecr_repository_arns = dependency.app.outputs.ecr_repository_arns
  ecr_repository_uris = dependency.app.outputs.ecr_repository_uris

  # Absolute path so archive_file works regardless of the terragrunt-cache
  # layout (same pattern used by interactive/_include.hcl for Lambda packages).
  codebuild_dispatcher_source_dir = "${get_repo_root()}/src/codebuild_dispatcher"

  # iam:PassRole scoping — CodeBuild may pass these task / runtime execution roles during deploy
  codebuild_pass_role_arns = compact([
    dependency.app.outputs.ecs_task_execution_role_arn,
    dependency.interactive.outputs.agentcore_runtime_role_arn,
    try(dependency.workloads.outputs.task_role_arns["cache_service"], ""),
    try(dependency.workloads.outputs.task_role_arns["llm_service"], ""),
    try(dependency.workloads.outputs.task_role_arns["messages_pusher"], ""),
  ])

  # Per-project env vars consumed by buildspec.yml (see src/<service>/buildspec.yml on ai_impl)
  codebuild_extra_env_vars = {
    agentcore = {
      AGENTCORE_RUNTIME_ID       = dependency.interactive.outputs.agentcore_runtime_id
      AGENTCORE_EXECUTION_ROLE_ARN = dependency.interactive.outputs.agentcore_runtime_role_arn
    }
    cache-service = {
      ECS_CLUSTER_NAME = dependency.app.outputs.ecs_cluster_name
      ECS_SERVICE_NAME = dependency.workloads.outputs.cache_service_name
      ECS_TASK_FAMILY  = dependency.workloads.outputs.cache_service_task_family
    }
    llm-service = {
      ECS_CLUSTER_NAME = dependency.app.outputs.ecs_cluster_name
      ECS_SERVICE_NAME = dependency.workloads.outputs.llm_service_name
      ECS_TASK_FAMILY  = dependency.workloads.outputs.llm_service_task_family
    }
    messages-pusher = {
      ECS_CLUSTER_NAME         = dependency.app.outputs.ecs_cluster_name
      MESSAGES_PUSHER_TASK_DEF = dependency.workloads.outputs.messages_pusher_task_definition_arn
      ECS_TASK_FAMILY          = dependency.workloads.outputs.messages_pusher_task_family
    }
    tei-embedding = {
      # TEI upstream tag chosen for the target SageMaker instance family:
      #   turing-1.6 = T4 / g4dn (current)
      #   86-1.6     = A10G / g5
      TEI_BASE_TAG = "turing-1.6"
    }
  }

  # Per-project extra IAM — ECS register-task-definition + update-service, AgentCore update
  codebuild_extra_iam_policies = {
    agentcore = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:UpdateAgentRuntime",
          "bedrock-agentcore:GetAgentRuntime",
          "bedrock-agentcore:ListAgentRuntimes",
          "bedrock-agentcore:CreateAgentRuntimeEndpoint",
          "bedrock-agentcore:GetAgentRuntimeEndpoint",
        ]
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = local.region_vars.aws_region } }
      }]
    })
    cache-service = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Effect = "Allow"
        Action = [
          "ecs:DescribeTaskDefinition",
          "ecs:RegisterTaskDefinition",
          "ecs:UpdateService",
          "ecs:DescribeServices",
          "ecs:DescribeTasks",
          "ecs:ListTasks",
        ]
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = local.region_vars.aws_region } }
      }]
    })
    llm-service = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Effect = "Allow"
        Action = [
          "ecs:DescribeTaskDefinition",
          "ecs:RegisterTaskDefinition",
          "ecs:UpdateService",
          "ecs:DescribeServices",
          "ecs:DescribeTasks",
          "ecs:ListTasks",
        ]
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = local.region_vars.aws_region } }
      }]
    })
    messages-pusher = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Effect = "Allow"
        Action = [
          "ecs:DescribeTaskDefinition",
          "ecs:RegisterTaskDefinition",
        ]
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = local.region_vars.aws_region } }
      }]
    })
  }

  # CodeBuild source version — all 5 projects build from this branch
  codebuild_source_version = local.region_vars.codebuild_source_ref
}
