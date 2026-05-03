locals {
  env = var.env
  # tflint-ignore: terraform_unused_declarations
  is_prod = var.env_type == "prod"

  # Name helper: format(local.name_fmt, "<prefix>", "<descriptive-name>")
  # Produces: "<prefix>-<project>-<env>-<descriptive-name>" (e.g., "alb-linkme-ai-poc")
  name_fmt   = "%s-${var.project_name}-${local.env}-%s"
  name_short = "%s-${var.project_name}-${local.env}"

  # Frontend flag
  enable_frontend = var.enable_frontend

  # Backend compute helpers
  has_backend       = var.backend_type != "none"
  is_agentcore      = var.backend_type == "agentcore"
  is_ecs_backend    = var.backend_type == "ecs"
  is_lambda_backend = var.backend_type == "lambda"

  backend_trust_services = {
    agentcore = "bedrock-agentcore.amazonaws.com"
    ecs       = "ecs-tasks.amazonaws.com"
    lambda    = "lambda.amazonaws.com"
  }

  # Keep resource names stable per backend type (avoids destroy/recreate)
  backend_role_suffix = {
    agentcore = "agentcore"
    ecs       = "backend-ecs"
    lambda    = "backend-lambda"
  }

  backend_sg_description = {
    agentcore = "Security group for AgentCore runtime"
    ecs       = "Security group for ECS backend service"
    lambda    = "Security group for Lambda backend function"
  }

  backend_log_prefix = {
    agentcore = "/aws/agentcore"
    ecs       = "/ecs"
    lambda    = "/aws/lambda"
  }

  # ECR KMS key policy - roles allowed to pull images
  ecr_kms_pull_role_arns = concat(
    [aws_iam_role.ecs_execution.arn],
    aws_iam_role.backend[*].arn,
  )

  # ECR repo push policies - only for repos with a known CI/CD role
  ecr_push_repos = {
    for k, v in var.ecr_push_role_arns : k => v
    if v != "" && contains(keys(var.ecr_repositories), k)
  }
}
