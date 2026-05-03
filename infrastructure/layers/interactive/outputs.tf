output "agentcore_runtime_arn" {
  description = "ARN of the AgentCore Runtime (empty when disabled)"
  value       = var.enable_agentcore_runtime ? aws_bedrockagentcore_agent_runtime.phase1[0].agent_runtime_arn : ""
}

output "agentcore_runtime_id" {
  description = "ID of the AgentCore Runtime (empty when disabled)"
  value       = var.enable_agentcore_runtime ? aws_bedrockagentcore_agent_runtime.phase1[0].agent_runtime_id : ""
}

output "agentcore_runtime_role_arn" {
  description = "AgentCore execution role ARN (empty when disabled)"
  value       = var.enable_agentcore_runtime ? aws_iam_role.agentcore[0].arn : ""
}

output "api_function_name" {
  description = "API Lambda function name (empty when disabled)"
  value       = var.enable_api_lambda ? aws_lambda_function.api[0].function_name : ""
}

output "api_function_url" {
  description = "API Lambda Function URL (empty when disabled)"
  value       = var.enable_api_lambda ? aws_lambda_function_url.api[0].function_url : ""
}

output "ddb_table_arns" {
  description = "Map of DDB table names to ARNs"
  value       = { for k, t in aws_dynamodb_table.this : k => t.arn }
}

output "ddb_table_names" {
  description = "Map of DDB table keys to names"
  value       = { for k, t in aws_dynamodb_table.this : k => t.name }
}

output "preprocessor_function_name" {
  description = "Preprocessing Lambda function name (empty when disabled)"
  value       = var.enable_preprocessor ? aws_lambda_function.preprocessor[0].function_name : ""
}

output "ui_bucket_domain" {
  description = "UI bucket website domain (empty when disabled)"
  value       = var.enable_ui_bucket ? aws_s3_bucket_website_configuration.ui[0].website_endpoint : ""
}

output "ui_bucket_name" {
  description = "UI bucket name (empty when disabled)"
  value       = var.enable_ui_bucket ? aws_s3_bucket.ui[0].bucket : ""
}
