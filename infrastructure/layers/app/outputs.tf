output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer - empty when enable_frontend is false"
  value       = local.enable_frontend ? aws_lb.this[0].dns_name : ""
}

output "alb_listener_arn" {
  description = "ARN of the HTTP ALB listener - empty when enable_frontend is false"
  value       = local.enable_frontend ? aws_lb_listener.http[0].arn : ""
}

output "alb_url" {
  description = "HTTP URL of the Application Load Balancer - empty when enable_frontend is false"
  value       = local.enable_frontend ? "http://${aws_lb.this[0].dns_name}" : ""
}

output "backend_ecs_service_name" {
  description = "Name of the backend ECS service - empty when backend_type is not ecs"
  value       = local.is_ecs_backend ? aws_ecs_service.backend[0].name : ""
}

output "backend_lambda_function_arn" {
  description = "ARN of the backend Lambda function - empty when backend_type is not lambda"
  value       = local.is_lambda_backend ? aws_lambda_function.backend[0].arn : ""
}

output "backend_lambda_function_name" {
  description = "Name of the backend Lambda function - empty when backend_type is not lambda"
  value       = local.is_lambda_backend ? aws_lambda_function.backend[0].function_name : ""
}

output "backend_log_group_name" {
  description = "Name of the backend CloudWatch log group - empty when no backend"
  value       = local.has_backend ? aws_cloudwatch_log_group.backend[0].name : ""
}

output "backend_role_arn" {
  description = "ARN of the backend IAM role - empty when backend_type is none"
  value       = local.has_backend ? aws_iam_role.backend[0].arn : ""
}

output "backend_security_group_id" {
  description = "ID of the backend security group - empty when backend_type is none"
  value       = local.has_backend ? aws_security_group.backend[0].id : ""
}

output "ecr_repository_arns" {
  description = "Map of ECR repository key to ARN"
  value       = { for k, v in aws_ecr_repository.this : k => v.arn }
}

output "ecr_repository_names" {
  description = "Map of ECR repository key to name"
  value       = { for k, v in aws_ecr_repository.this : k => v.name }
}

output "ecr_repository_uris" {
  description = "Map of ECR repository key to URI"
  value       = { for k, v in aws_ecr_repository.this : k => v.repository_url }
}

output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster"
  value       = aws_ecs_cluster.this.arn
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = aws_ecs_cluster.this.name
}

output "ecs_security_group_id" {
  description = "ID of the ECS frontend tasks security group - empty when enable_frontend is false"
  value       = local.enable_frontend ? aws_security_group.ecs[0].id : ""
}

output "ecs_task_execution_role_arn" {
  description = "ARN of the ECS task execution IAM role"
  value       = aws_iam_role.ecs_execution.arn
}

output "ecs_task_role_arn" {
  description = "ARN of the ECS frontend task IAM role - empty when enable_frontend is false"
  value       = local.enable_frontend ? aws_iam_role.ecs_task[0].arn : ""
}

output "frontend_target_group_arn" {
  description = "ARN of the frontend ALB target group - empty when enable_frontend is false"
  value       = local.enable_frontend ? aws_lb_target_group.frontend[0].arn : ""
}
