resource "aws_security_group" "task" {
  count = var.enable_workloads ? 1 : 0

  name        = format(local.name_fmt, "sgr", "workloads-task")
  description = "Egress for Phase 2 ECS tasks cache-service llm-service messages-pusher"
  vpc_id      = var.vpc_id

  tags = {
    Name        = format(local.name_fmt, "sgr", "workloads-task")
    Description = "ECS Fargate task ENIs for Phase 2 workloads"
  }
}

resource "aws_vpc_security_group_egress_rule" "task_all" {
  count = var.enable_workloads ? 1 : 0

  security_group_id = aws_security_group.task[0].id
  description       = "Egress to AWS endpoints and internet for Bedrock SageMaker DDB SQS S3 ECR"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"

  tags = {
    Name        = format(local.name_fmt, "sgr", "workloads-task-egress-all")
    Description = "All egress POC"
  }
}

resource "aws_vpc_security_group_ingress_rule" "memorydb_from_tasks" {
  count = var.enable_workloads ? 1 : 0

  security_group_id            = var.memorydb_security_group_id
  referenced_security_group_id = aws_security_group.task[0].id
  description                  = "Allow MemoryDB access from Phase 2 workloads tasks"
  from_port                    = var.memorydb_port
  to_port                      = var.memorydb_port
  ip_protocol                  = "tcp"

  tags = {
    Name        = format(local.name_fmt, "sgr", "memorydb-from-tasks")
    Description = "Ingress to MemoryDB from task SG"
  }
}
