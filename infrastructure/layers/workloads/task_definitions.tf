resource "aws_cloudwatch_log_group" "service" {
  for_each = var.enable_workloads ? var.workloads_task_config : {}

  name              = "/ecs/${var.project_name}/${var.env}/${each.value.name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = format(local.name_fmt, "log", each.value.name)
    Description = "ECS task logs for ${each.value.name}"
  }
}

# ================================================================
# cache-service task definition (ECS Fargate ARM64)
# ================================================================
resource "aws_ecs_task_definition" "cache_service" {
  count = var.enable_workloads ? 1 : 0

  family                   = format(local.name_fmt, "task", "cache-service")
  cpu                      = tostring(var.workloads_task_config.cache_service.cpu)
  memory                   = tostring(var.workloads_task_config.cache_service.memory)
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = var.ecs_task_execution_role_arn
  task_role_arn            = aws_iam_role.task["cache_service"].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = "cache-service"
    image     = "${var.ecr_repository_uris[var.workloads_task_config.cache_service.ecr_repo_key]}:latest"
    essential = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service["cache_service"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "cache"
      }
    }
    environment = [
      { name = "AWS_REGION", value = var.region },
      { name = "INCOMING_QUEUE_URL", value = var.incoming_queue_url },
      { name = "AI_PROCESSING_QUEUE_URL", value = var.ai_processing_queue_url },
      { name = "RESULTS_TABLE", value = var.results_table_name },
      { name = "SAGEMAKER_ENDPOINT_NAME", value = var.sagemaker_endpoint_name },
      { name = "MEMORYDB_ENDPOINT", value = var.memorydb_endpoint },
      { name = "MEMORYDB_PORT", value = tostring(var.memorydb_port) },
      { name = "WORKER_COUNT", value = tostring(coalesce(var.workloads_task_config.cache_service.worker_count, 6)) },
    ]
  }])

  tags = {
    Name        = format(local.name_fmt, "task", "cache-service")
    Description = "Cache Service ECS Fargate task definition"
  }
}

# ================================================================
# llm-service task definition (ECS Fargate ARM64)
# ================================================================
resource "aws_ecs_task_definition" "llm_service" {
  count = var.enable_workloads ? 1 : 0

  family                   = format(local.name_fmt, "task", "llm-service")
  cpu                      = tostring(var.workloads_task_config.llm_service.cpu)
  memory                   = tostring(var.workloads_task_config.llm_service.memory)
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = var.ecs_task_execution_role_arn
  task_role_arn            = aws_iam_role.task["llm_service"].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = "llm-service"
    image     = "${var.ecr_repository_uris[var.workloads_task_config.llm_service.ecr_repo_key]}:latest"
    essential = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service["llm_service"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "llm"
      }
    }
    environment = [
      { name = "AWS_REGION", value = var.region },
      { name = "AI_PROCESSING_QUEUE_URL", value = var.ai_processing_queue_url },
      { name = "RESULTS_TABLE", value = var.results_table_name },
      { name = "BEDROCK_KB_ID", value = var.knowledge_base_id },
      { name = "BEDROCK_KB_DS_ID", value = var.knowledge_base_data_source_id },
      { name = "KB_ID", value = var.knowledge_base_id },
      { name = "SAGEMAKER_ENDPOINT_NAME", value = var.sagemaker_endpoint_name },
      { name = "MEMORYDB_ENDPOINT", value = var.memorydb_endpoint },
      { name = "MEMORYDB_PORT", value = tostring(var.memorydb_port) },
    ]
  }])

  tags = {
    Name        = format(local.name_fmt, "task", "llm-service")
    Description = "LLM Service ECS Fargate task definition"
  }
}

# ================================================================
# messages-pusher task definition (operator-triggered run-task)
# ================================================================
resource "aws_ecs_task_definition" "messages_pusher" {
  count = var.enable_workloads ? 1 : 0

  family                   = format(local.name_fmt, "task", "messages-pusher")
  cpu                      = tostring(var.workloads_task_config.messages_pusher.cpu)
  memory                   = tostring(var.workloads_task_config.messages_pusher.memory)
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = var.ecs_task_execution_role_arn
  task_role_arn            = aws_iam_role.task["messages_pusher"].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = "messages-pusher"
    image     = "${var.ecr_repository_uris[var.workloads_task_config.messages_pusher.ecr_repo_key]}:latest"
    essential = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service["messages_pusher"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "pusher"
      }
    }
    environment = [
      { name = "AWS_REGION", value = var.region },
      { name = "INPUT_MESSAGES_BUCKET", value = var.input_messages_bucket },
      { name = "INCOMING_QUEUE_URL", value = var.incoming_queue_url },
    ]
  }])

  tags = {
    Name        = format(local.name_fmt, "task", "messages-pusher")
    Description = "Messages Pusher ECS Fargate task definition operator-triggered run-task"
  }
}
