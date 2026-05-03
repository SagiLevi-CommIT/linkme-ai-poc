resource "aws_ecs_service" "cache_service" {
  count = var.enable_workloads ? 1 : 0

  name            = format(local.name_fmt, "svc", "cache-service")
  cluster         = var.ecs_cluster_arn
  task_definition = aws_ecs_task_definition.cache_service[0].arn
  desired_count   = var.workloads_task_config.cache_service.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [aws_security_group.task[0].id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name        = format(local.name_fmt, "svc", "cache-service")
    Description = "Cache Service long-running ECS Fargate service"
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

resource "aws_ecs_service" "llm_service" {
  count = var.enable_workloads ? 1 : 0

  name            = format(local.name_fmt, "svc", "llm-service")
  cluster         = var.ecs_cluster_arn
  task_definition = aws_ecs_task_definition.llm_service[0].arn
  desired_count   = var.workloads_task_config.llm_service.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [aws_security_group.task[0].id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name        = format(local.name_fmt, "svc", "llm-service")
    Description = "LLM Service long-running ECS Fargate service"
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}
