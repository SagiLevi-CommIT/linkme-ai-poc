variable "account_id" {
  type        = string
  description = "AWS account ID for allowed_account_ids provider guard and IAM policy ARNs"
}

variable "ddb_results_config" {
  type = object({
    table_name = string
    gsi_name   = string
    ttl_attr   = string
  })
  description = "Config for the Phase 2 results DDB table"
}

variable "enable_memorydb" {
  type        = bool
  description = "Create MemoryDB for Redis cluster"
  default     = true
}

variable "enable_messaging" {
  type        = bool
  description = "Create SQS queues, results DDB, input-messages bucket"
  default     = true
}

variable "env" {
  type        = string
  description = "Environment name"
}

variable "memorydb_config" {
  type = object({
    node_type                = string
    engine_version           = string
    num_shards               = number
    num_replicas_per_shard   = number
    port                     = number
    snapshot_retention_limit = number
    maintenance_window       = string
    parameter_group_family   = string
  })
  description = "MemoryDB cluster configuration (Redis 7.1+ baseline)"
}

variable "private_db_subnet_ids" {
  type        = list(string)
  description = "Private db subnet IDs for MemoryDB subnet group"
}

variable "project_name" {
  type        = string
  description = "Project name"
}

variable "region" {
  type        = string
  description = "AWS region"
}

variable "s3_input_messages_bucket" {
  type        = string
  description = "S3 bucket name for Phase 2 simulator input JSONL batches"
}

variable "simulator_dashboard_name" {
  type        = string
  description = "CloudWatch dashboard name for the simulator"
}

variable "sqs_config" {
  type = object({
    message_retention_seconds        = number
    dlq_max_receive_count            = number
    incoming_visibility_timeout      = number
    ai_processing_visibility_timeout = number
  })
  description = "SQS queue configuration"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}
