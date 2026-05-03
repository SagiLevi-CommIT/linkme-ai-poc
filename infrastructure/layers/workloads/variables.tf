variable "account_id" {
  type        = string
  description = "AWS account ID for allowed_account_ids provider guard"
}

variable "ai_processing_queue_arn" {
  type        = string
  description = "AI processing FIFO queue ARN (llm-service consumer)"
}

variable "ai_processing_queue_url" {
  type        = string
  description = "AI processing FIFO queue URL"
}

variable "bedrock_inference_profile_arns" {
  type        = list(string)
  description = "US CRIS inference profile ARNs (Haiku Sonnet Nova)"
  default     = []
}

variable "bedrock_model_arns" {
  type        = list(string)
  description = "Bedrock foundation model ARNs for llm-service access"
  default     = []
}

variable "ecr_repository_uris" {
  type        = map(string)
  description = "Map of ECR repository keys to URIs (from app layer)"
}

variable "ecs_cluster_arn" {
  type        = string
  description = "ECS cluster ARN (from app layer)"
}

variable "ecs_cluster_name" {
  type        = string
  description = "ECS cluster name"
}

variable "ecs_task_execution_role_arn" {
  type        = string
  description = "Shared ECS task execution role ARN (from app layer)"
}

variable "enable_autoscaling" {
  type        = bool
  description = "Create Application Auto Scaling target-tracking and step-scaling policies"
  default     = true
}

variable "enable_workloads" {
  type        = bool
  description = "Create ECS task definitions and services"
  default     = true
}

variable "env" {
  type        = string
  description = "Environment name (used in resource names)"
}

variable "incoming_queue_arn" {
  type        = string
  description = "Incoming standard queue ARN (cache-service consumer)"
}

variable "incoming_queue_url" {
  type        = string
  description = "Incoming standard queue URL"
}

variable "input_messages_bucket" {
  type        = string
  description = "S3 input-messages bucket name (messages-pusher reads from here)"
}

variable "input_messages_bucket_arn" {
  type        = string
  description = "S3 input-messages bucket ARN"
}

variable "knowledge_base_id" {
  type        = string
  description = "Bedrock Knowledge Base ID for llm-service retrieval"
}

variable "knowledge_base_data_source_id" {
  type        = string
  description = "Bedrock Knowledge Base data source ID for llm-service runtime metadata"
  default     = ""
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention"
  default     = 7
}

variable "memorydb_endpoint" {
  type        = string
  description = "MemoryDB cluster endpoint hostname"
}

variable "memorydb_port" {
  type        = number
  description = "MemoryDB port"
  default     = 6379
}

variable "memorydb_security_group_id" {
  type        = string
  description = "Security group ID protecting MemoryDB (we add an ingress rule from task SG)"
}

variable "phase1_ddb_table_arns" {
  type        = list(string)
  description = "DDB table ARNs from interactive layer (profiles, cache, messages, semantic-cache) - read/write by llm-service and cache-service"
  default     = []
}

variable "private_app_subnet_ids" {
  type        = list(string)
  description = "Private app subnet IDs for task ENIs"
}

variable "project_name" {
  type        = string
  description = "Project name"
}

variable "region" {
  type        = string
  description = "AWS region"
}

variable "results_table_arn" {
  type        = string
  description = "DDB Results table ARN"
}

variable "results_table_name" {
  type        = string
  description = "DDB Results table name"
}

variable "sagemaker_endpoint_arn" {
  type        = string
  description = "SageMaker embedding endpoint ARN"
}

variable "sagemaker_endpoint_name" {
  type        = string
  description = "SageMaker embedding endpoint name"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "workloads_task_config" {
  type = map(object({
    name            = string
    ecr_repo_key    = string
    cpu             = number
    memory          = number
    desired_count   = optional(number)
    min_capacity    = optional(number)
    max_capacity    = optional(number)
    sqs_target_msgs = optional(number)
    # Cache-service only: number of concurrent embed-and-search workers per
    # task. Sized against the SageMaker endpoint's burst capacity so that
    # total_tasks x worker_count stays below the per-instance invocation
    # ceiling that triggers autoscale-out.
    worker_count = optional(number)
  }))
  description = "Per-service task + service + autoscaling config (cache_service llm_service messages_pusher)"
}
