output "ai_processing_dlq_arn" {
  description = "AI processing FIFO DLQ ARN"
  value       = local.enable_messaging ? aws_sqs_queue.ai_processing_dlq[0].arn : ""
}

output "ai_processing_queue_arn" {
  description = "AI processing FIFO queue ARN"
  value       = local.enable_messaging ? aws_sqs_queue.ai_processing[0].arn : ""
}

output "ai_processing_queue_url" {
  description = "AI processing FIFO queue URL"
  value       = local.enable_messaging ? aws_sqs_queue.ai_processing[0].url : ""
}

output "incoming_dlq_arn" {
  description = "Incoming DLQ ARN"
  value       = local.enable_messaging ? aws_sqs_queue.incoming_dlq[0].arn : ""
}

output "incoming_queue_arn" {
  description = "Incoming standard queue ARN"
  value       = local.enable_messaging ? aws_sqs_queue.incoming[0].arn : ""
}

output "incoming_queue_url" {
  description = "Incoming standard queue URL"
  value       = local.enable_messaging ? aws_sqs_queue.incoming[0].url : ""
}

output "input_messages_bucket" {
  description = "S3 input-messages bucket name"
  value       = local.enable_messaging ? aws_s3_bucket.input_messages[0].bucket : ""
}

output "input_messages_bucket_arn" {
  description = "S3 input-messages bucket ARN"
  value       = local.enable_messaging ? aws_s3_bucket.input_messages[0].arn : ""
}

output "memorydb_endpoint" {
  description = "MemoryDB cluster endpoint hostname"
  value       = local.enable_memorydb ? tolist(aws_memorydb_cluster.this[0].cluster_endpoint)[0].address : ""
}

output "memorydb_port" {
  description = "MemoryDB cluster port"
  value       = local.enable_memorydb ? var.memorydb_config.port : 0
}

output "memorydb_security_group_id" {
  description = "MemoryDB security group ID (workloads layer adds task-ingress rules)"
  value       = local.enable_memorydb ? aws_security_group.memorydb[0].id : ""
}

output "results_table_arn" {
  description = "DDB Results table ARN"
  value       = local.enable_messaging ? aws_dynamodb_table.results[0].arn : ""
}

output "results_table_name" {
  description = "DDB Results table name"
  value       = local.enable_messaging ? aws_dynamodb_table.results[0].name : ""
}

output "simulator_dashboard_name" {
  description = "CloudWatch simulator dashboard name"
  value       = local.enable_messaging ? aws_cloudwatch_dashboard.simulator[0].dashboard_name : ""
}
