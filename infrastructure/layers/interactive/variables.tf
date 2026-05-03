variable "account_id" {
  type        = string
  description = "AWS account ID for allowed_account_ids provider guard"
}

variable "agentcore_ecr_repository_url" {
  type        = string
  description = "ECR repository URL for the AgentCore Runtime container image (without tag)"
}

variable "agentcore_runtime_config" {
  type = object({
    runtime_name = string
    endpoint_id  = string
    network_mode = string
    ecr_repo_key = string
  })
  description = "AgentCore Runtime settings (name, endpoint id, network mode, ECR repo key)"
}

variable "api_lambda_config" {
  type = object({
    function_name = string
    runtime       = string
    memory_mb     = number
    timeout_s     = number
    package_path  = string
    handler       = string
  })
  description = "API Lambda configuration"
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "Optional KMS CMK ARN for CloudWatch Logs encryption (null to use AWS-managed key)"
  default     = null
}

variable "ddb_tables" {
  type = map(object({
    name         = string
    hash_key     = string
    billing_mode = string
  }))
  description = "Phase 1 interactive DynamoDB tables (profiles, cache, messages, semantic_cache)"
}

variable "enable_agentcore_runtime" {
  type        = bool
  description = "Create the AgentCore Runtime + IAM"
  default     = true
}

variable "enable_api_lambda" {
  type        = bool
  description = "Create the API Lambda + Function URL"
  default     = true
}

variable "enable_preprocessor" {
  type        = bool
  description = "Create the Preprocessing Lambda + S3 event notification"
  default     = true
}

variable "enable_ui_bucket" {
  type        = bool
  description = "Create the S3 static UI bucket"
  default     = true
}

variable "env" {
  type        = string
  description = "Environment name (used in resource names)"
}

variable "incoming_queue_arn" {
  type        = string
  description = "Incoming SQS queue ARN (API Lambda enqueues here on submit-question)"
}

variable "incoming_queue_url" {
  type        = string
  description = "Incoming SQS queue URL"
}

variable "kb_source_bucket_name" {
  type        = string
  description = "Bedrock KB source S3 bucket (preprocessing writes normalized text here)"
}

variable "knowledge_base_id" {
  type        = string
  description = "Bedrock Knowledge Base ID (preprocessing calls StartIngestionJob)"
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention in days"
  default     = 7
}

variable "preprocessor_lambda_config" {
  type = object({
    function_name = string
    runtime       = string
    memory_mb     = number
    timeout_s     = number
    package_path  = string
    handler       = string
  })
  description = "Preprocessing Lambda configuration"
}

variable "raw_uploads_bucket_arn" {
  type        = string
  description = "Raw uploads bucket ARN (source of S3 event notifications)"
}

variable "raw_uploads_bucket_name" {
  type        = string
  description = "Raw uploads bucket name"
}

variable "region" {
  type        = string
  description = "AWS region"
}

variable "results_table_arn" {
  type        = string
  description = "DDB Results table ARN (API Lambda reads for polling)"
}

variable "results_table_name" {
  type        = string
  description = "DDB Results table name"
}

variable "ui_bucket_name" {
  type        = string
  description = "S3 static UI bucket name"
}
