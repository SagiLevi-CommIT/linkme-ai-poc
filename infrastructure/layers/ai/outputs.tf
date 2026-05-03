output "agent_alias_id" {
  description = "Alias ID of the Bedrock Agent (empty when disabled)"
  value       = local.enable_agent ? aws_bedrockagent_agent_alias.this[0].agent_alias_id : ""
}

output "agent_arn" {
  description = "ARN of the Bedrock Agent"
  value       = local.enable_agent ? aws_bedrockagent_agent.this[0].agent_arn : ""
}

output "agent_id" {
  description = "ID of the Bedrock Agent"
  value       = local.enable_agent ? aws_bedrockagent_agent.this[0].agent_id : ""
}

output "agent_role_arn" {
  description = "IAM role ARN for the Bedrock Agent"
  value       = local.enable_agent ? aws_iam_role.agent[0].arn : ""
}

output "kb_role_arn" {
  description = "IAM role ARN for the Knowledge Base"
  value       = local.enable_knowledge_base ? aws_iam_role.kb[0].arn : ""
}

output "kb_source_bucket_arn" {
  description = "ARN of the KB source S3 bucket"
  value       = aws_s3_bucket.kb_source.arn
}

output "kb_source_bucket_name" {
  description = "Name of the KB source S3 bucket"
  value       = aws_s3_bucket.kb_source.bucket
}

output "knowledge_base_arn" {
  description = "ARN of the Bedrock Knowledge Base"
  value       = local.enable_knowledge_base ? aws_bedrockagent_knowledge_base.this[0].arn : ""
}

output "knowledge_base_id" {
  description = "ID of the Bedrock Knowledge Base"
  value       = local.enable_knowledge_base ? aws_bedrockagent_knowledge_base.this[0].id : ""
}

output "raw_uploads_bucket_arn" {
  description = "ARN of the raw-uploads S3 bucket"
  value       = aws_s3_bucket.raw_uploads.arn
}

output "raw_uploads_bucket_name" {
  description = "Name of the raw-uploads S3 bucket"
  value       = aws_s3_bucket.raw_uploads.bucket
}

output "sagemaker_endpoint_arn" {
  description = "SageMaker embedding endpoint ARN"
  value       = local.enable_sagemaker ? aws_sagemaker_endpoint.embedding[0].arn : ""
}

output "sagemaker_endpoint_name" {
  description = "SageMaker embedding endpoint name"
  value       = local.enable_sagemaker ? aws_sagemaker_endpoint.embedding[0].name : ""
}

output "sagemaker_model_name" {
  description = "SageMaker model name"
  value       = local.enable_sagemaker ? aws_sagemaker_model.tei[0].name : ""
}

output "vector_bucket_name" {
  description = "S3 Vectors bucket name"
  value       = local.enable_knowledge_base ? aws_s3vectors_vector_bucket.this[0].vector_bucket_name : ""
}

output "vector_index_arn" {
  description = "S3 Vectors index ARN"
  value       = local.enable_knowledge_base ? aws_s3vectors_index.this[0].index_arn : ""
}
