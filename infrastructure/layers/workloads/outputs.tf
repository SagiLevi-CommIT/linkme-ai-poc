output "cache_service_name" {
  description = "Cache Service ECS service name (empty when disabled)"
  value       = var.enable_workloads ? aws_ecs_service.cache_service[0].name : ""
}

output "cache_service_task_definition_arn" {
  description = "Cache Service task definition ARN"
  value       = var.enable_workloads ? aws_ecs_task_definition.cache_service[0].arn : ""
}

output "cache_service_task_family" {
  description = "Cache Service task definition family name"
  value       = var.enable_workloads ? aws_ecs_task_definition.cache_service[0].family : ""
}

output "llm_service_name" {
  description = "LLM Service ECS service name"
  value       = var.enable_workloads ? aws_ecs_service.llm_service[0].name : ""
}

output "llm_service_task_definition_arn" {
  description = "LLM Service task definition ARN"
  value       = var.enable_workloads ? aws_ecs_task_definition.llm_service[0].arn : ""
}

output "llm_service_task_family" {
  description = "LLM Service task definition family name"
  value       = var.enable_workloads ? aws_ecs_task_definition.llm_service[0].family : ""
}

output "messages_pusher_task_definition_arn" {
  description = "Messages Pusher task definition ARN (operator runs via aws ecs run-task)"
  value       = var.enable_workloads ? aws_ecs_task_definition.messages_pusher[0].arn : ""
}

output "messages_pusher_task_family" {
  description = "Messages Pusher task definition family name"
  value       = var.enable_workloads ? aws_ecs_task_definition.messages_pusher[0].family : ""
}

output "task_role_arns" {
  description = "Map of task key to task role ARN (for CodeBuild iam:PassRole scoping in cicd layer)"
  value       = { for k, r in aws_iam_role.task : k => r.arn }
}

output "task_security_group_id" {
  description = "Task ENI security group ID"
  value       = var.enable_workloads ? aws_security_group.task[0].id : ""
}
