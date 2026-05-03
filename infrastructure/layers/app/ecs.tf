# ============================================================
# ECS Cluster (shared platform for frontend and optional ECS backend)
# ============================================================

resource "aws_ecs_cluster" "this" {
  name = format(local.name_fmt, "ecs", "cluster")

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name        = format(local.name_fmt, "ecs", "cluster")
    Description = "ECS cluster for ${var.project_name} ${var.env} workloads"
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name = aws_ecs_cluster.this.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# ============================================================
# CloudWatch Log Groups
# ============================================================

resource "aws_cloudwatch_log_group" "frontend" {
  count             = local.enable_frontend ? 1 : 0
  name              = "/ecs/${var.project_name}-${var.env}-frontend"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.cloudwatch_kms_key_arn

  tags = {
    Name        = format(local.name_fmt, "log", "ecs-frontend")
    Description = "CloudWatch log group for ECS frontend tasks"
  }
}

resource "aws_cloudwatch_log_group" "backend" {
  count             = local.has_backend ? 1 : 0
  name              = "${local.backend_log_prefix[var.backend_type]}/${var.project_name}-${var.env}-backend"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.cloudwatch_kms_key_arn

  tags = {
    Name        = format(local.name_fmt, "log", "${var.backend_type}-backend")
    Description = "CloudWatch log group for ${var.backend_type} backend"
  }
}

# ============================================================
# ECS Backend Service (only when backend_type = ecs)
# Deploy with desired_count = 0 initially, set to 1+ after pushing
# a container image to ECR.
# ============================================================

resource "aws_ecs_task_definition" "backend" {
  count  = local.is_ecs_backend ? 1 : 0
  family = "${var.project_name}-${var.env}-backend"

  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.backend_ecs_config.cpu
  memory                   = var.backend_ecs_config.memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.backend[0].arn

  container_definitions = jsonencode([{
    name      = "backend"
    image     = "${aws_ecr_repository.this[var.backend_ecs_config.ecr_repo_key].repository_url}:${var.backend_ecs_config.image_tag}"
    essential = true
    portMappings = [{
      containerPort = var.backend_container_port
      protocol      = "tcp"
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend[0].name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])

  tags = {
    Name        = format(local.name_fmt, "taskdef", "backend")
    Description = "ECS task definition for ${var.project_name} backend"
  }

  lifecycle {
    precondition {
      condition     = contains(keys(var.ecr_repositories), var.backend_ecs_config.ecr_repo_key)
      error_message = "backend_ecs_config.ecr_repo_key \"${var.backend_ecs_config.ecr_repo_key}\" not found in var.ecr_repositories. Valid keys: ${join(", ", keys(var.ecr_repositories))}."
    }
  }
}

resource "aws_ecs_service" "backend" {
  count           = local.is_ecs_backend ? 1 : 0
  name            = "${var.project_name}-${var.env}-backend-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.backend[0].arn
  desired_count   = var.backend_ecs_config.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [aws_security_group.backend[0].id]
    assign_public_ip = false
  }

  tags = {
    Name        = format(local.name_fmt, "ecs-svc", "backend")
    Description = "ECS service for ${var.project_name} backend"
  }
}

# ============================================================
# Lambda Backend (only when backend_type = lambda)
# Requires a container image in ECR before apply.
# ============================================================

resource "aws_lambda_function" "backend" {
  count         = local.is_lambda_backend ? 1 : 0
  function_name = format(local.name_fmt, "lambda", "backend")
  role          = aws_iam_role.backend[0].arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.this[var.backend_lambda_config.ecr_repo_key].repository_url}:${var.backend_lambda_config.image_tag}"
  architectures = var.backend_lambda_config.architectures
  timeout       = var.backend_lambda_config.timeout
  memory_size   = var.backend_lambda_config.memory_size

  dynamic "vpc_config" {
    for_each = length(var.private_app_subnet_ids) > 0 ? [1] : []
    content {
      subnet_ids         = var.private_app_subnet_ids
      security_group_ids = [aws_security_group.backend[0].id]
    }
  }

  tags = {
    Name        = format(local.name_fmt, "lambda", "backend")
    Description = "Lambda backend function for ${var.project_name} ${var.env}"
  }

  lifecycle {
    precondition {
      condition     = contains(keys(var.ecr_repositories), var.backend_lambda_config.ecr_repo_key)
      error_message = "backend_lambda_config.ecr_repo_key \"${var.backend_lambda_config.ecr_repo_key}\" not found in var.ecr_repositories. Valid keys: ${join(", ", keys(var.ecr_repositories))}."
    }
  }
}
