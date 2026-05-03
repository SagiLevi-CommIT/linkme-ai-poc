# ============================================================
# ECS Task Execution Role (always created - pulls images, writes logs)
# ============================================================

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name = format(local.name_fmt, "role", "ecs-execution")

  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = {
    Name        = format(local.name_fmt, "role", "ecs-execution")
    Description = "ECS task execution role - pulls images and writes logs"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ============================================================
# ECS Task Role (for frontend tasks)
# ============================================================

resource "aws_iam_role" "ecs_task" {
  count = local.enable_frontend ? 1 : 0
  name  = format(local.name_fmt, "role", "ecs-task")

  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = {
    Name        = format(local.name_fmt, "role", "ecs-task")
    Description = "ECS task role - runtime access for frontend tasks"
  }
}

resource "aws_iam_role_policy" "ecs_task_cloudwatch" {
  count = local.enable_frontend ? 1 : 0
  name  = "CloudWatchLogs"
  role  = aws_iam_role.ecs_task[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          aws_cloudwatch_log_group.frontend[0].arn,
          "${aws_cloudwatch_log_group.frontend[0].arn}:*",
        ]
      }
    ]
  })
}

# Frontend → AgentCore access (only when backend_type = agentcore)
resource "aws_iam_role_policy" "ecs_task_agentcore" {
  count = local.enable_frontend && local.is_agentcore ? 1 : 0
  name  = "AgentCoreAccess"
  role  = aws_iam_role.ecs_task[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        # bedrock-agentcore does not yet support resource-level ARN scoping in IAM.
        # Region + account conditions are the tightest controls currently available.
        # ListRuntimes omitted - the frontend only needs to invoke and describe its own runtime.
        Action = [
          "bedrock-agentcore:InvokeAgentRuntime",
          "bedrock-agentcore:GetRuntime",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestedRegion"  = var.region
            "aws:PrincipalAccount" = var.account_id
          }
        }
      }
    ]
  })
}

# Frontend → Lambda invoke (only when backend_type = lambda)
resource "aws_iam_role_policy" "ecs_task_lambda_invoke" {
  count = local.enable_frontend && local.is_lambda_backend ? 1 : 0
  name  = "LambdaInvokeAccess"
  role  = aws_iam_role.ecs_task[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = aws_lambda_function.backend[0].arn
      }
    ]
  })
}

# ============================================================
# Backend Role (conditional - created for agentcore, ecs, lambda)
# Trust policy varies by backend_type; policies are shared.
# ============================================================

data "aws_iam_policy_document" "backend_assume" {
  count = local.has_backend ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = [local.backend_trust_services[var.backend_type]]
    }
  }
}

resource "aws_iam_role" "backend" {
  count = local.has_backend ? 1 : 0
  name  = format(local.name_fmt, "role", local.backend_role_suffix[var.backend_type])

  assume_role_policy = data.aws_iam_policy_document.backend_assume[0].json

  tags = {
    Name        = format(local.name_fmt, "role", local.backend_role_suffix[var.backend_type])
    Description = "Backend execution role ${var.backend_type} - ${var.project_name} ${var.env}"
  }
}

# CloudWatch Logs
resource "aws_iam_role_policy" "backend_cloudwatch" {
  count = local.has_backend ? 1 : 0
  name  = "CloudWatchLogs"
  role  = aws_iam_role.backend[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          aws_cloudwatch_log_group.backend[0].arn,
          "${aws_cloudwatch_log_group.backend[0].arn}:*",
        ]
      }
    ]
  })
}

# Bedrock Models (when bedrock_model_arns is provided)
resource "aws_iam_role_policy" "backend_bedrock" {
  count = local.has_backend && length(var.bedrock_model_arns) > 0 ? 1 : 0
  name  = "BedrockAccess"
  role  = aws_iam_role.backend[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ]
        Resource = concat(
          var.bedrock_model_arns,
          ["arn:aws:bedrock:*:${var.account_id}:inference-profile/*"],
        )
      }
    ]
  })
}

# S3 Data Buckets (when s3_data_buckets is provided)
resource "aws_iam_role_policy" "backend_s3" {
  count = local.has_backend && length(var.s3_data_buckets) > 0 ? 1 : 0
  name  = "S3Access"
  role  = aws_iam_role.backend[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = [for name in values(var.s3_data_buckets) : "arn:aws:s3:::${name}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [for name in values(var.s3_data_buckets) : "arn:aws:s3:::${name}"]
      }
    ]
  })
}

# ECR Pull (AgentCore only - ECS uses execution role, Lambda uses service)
resource "aws_iam_role_policy" "backend_ecr" {
  count = local.is_agentcore ? 1 : 0
  name  = "ECRAccess"
  role  = aws_iam_role.backend[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # ecr:GetAuthorizationToken is a global action - cannot be scoped to a specific resource ARN
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
        ]
        Resource = [for v in aws_ecr_repository.this : v.arn]
      }
    ]
  })
}

# Bedrock Knowledge Base (when enabled)
resource "aws_iam_role_policy" "backend_knowledge_base" {
  count = local.has_backend && var.enable_bedrock_knowledge_base ? 1 : 0
  name  = "KnowledgeBaseAccess"
  role  = aws_iam_role.backend[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:RetrieveAndGenerate",
          "bedrock:Retrieve",
          "bedrock:GetKnowledgeBase",
        ]
        Resource = "arn:aws:bedrock:${var.region}:${var.account_id}:knowledge-base/*"
      }
    ]
  })
}

# Lambda VPC access (Lambda only, when subnets provided)
resource "aws_iam_role_policy_attachment" "backend_lambda_vpc" {
  count      = local.is_lambda_backend && length(var.private_app_subnet_ids) > 0 ? 1 : 0
  role       = aws_iam_role.backend[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}
