variable "account_id" {
  type        = string
  description = "AWS account ID for allowed_account_ids provider guard and IAM policy ARNs"
}

variable "agent_foundation_model" {
  type        = string
  description = "Foundation model ID for the Bedrock Agent preview path"
  default     = "anthropic.claude-sonnet-4-6"
}

variable "agent_idle_session_ttl" {
  type        = number
  description = "Idle session TTL in seconds for the Bedrock Agent"
  default     = 600
}

variable "agent_instruction" {
  type        = string
  description = "Instructions for the Bedrock Agent preview path"

  validation {
    condition     = length(var.agent_instruction) >= 40 && length(var.agent_instruction) <= 20000
    error_message = "Agent instruction must be between 40 and 20000 characters."
  }
}

variable "embedding_model_arn" {
  type        = string
  description = "ARN of the Titan V2 embedding model for the Bedrock Knowledge Base"
  default     = "arn:aws:bedrock:us-west-2::foundation-model/amazon.titan-embed-text-v2:0"
}

variable "enable_agent" {
  type        = bool
  description = "Create the Bedrock Agent + alias (preview path)"
  default     = true
}

variable "enable_knowledge_base" {
  type        = bool
  description = "Create the Bedrock Knowledge Base with S3 Vectors storage"
  default     = true
}

variable "enable_sagemaker" {
  type        = bool
  description = "Create the SageMaker embedding endpoint (bge-base-en-v1.5)"
  default     = true
}

variable "env" {
  type        = string
  description = "Environment short name"
}

variable "kb_source_bucket_name" {
  type        = string
  description = "S3 bucket name for the KB source (normalized text under tenant prefixes)"
  default     = "linkme-poc-kb-source"
}

variable "project_name" {
  type        = string
  description = "Project name used in resource naming"
}

variable "raw_uploads_bucket_name" {
  type        = string
  description = "S3 bucket name for raw uploads (pre-preprocessing)"
  default     = "linkme-poc-raw-uploads"
}

variable "region" {
  type        = string
  description = "AWS region"
}

variable "sagemaker_embedding" {
  type = object({
    endpoint_name     = string
    model_name        = string
    config_name       = string
    instance_type     = string
    initial_count     = number
    huggingface_model = string
    embedding_dim     = number
    # Exact TEI wrapper image tag in the tei-embedding ECR repo. Bump
    # after a CodeBuild run to roll the endpoint onto a new image.
    # Format: <TEI_BASE_TAG>-sm-<git-sha12>, e.g. turing-1.6-sm-85cd7334e5d5.
    image_tag                                   = string
    enable_autoscaling                          = bool
    autoscaling_min                             = optional(number, 1)
    autoscaling_max                             = optional(number, 8)
    autoscaling_target_invocations_per_instance = optional(number, 300)
  })
  description = "SageMaker embedding endpoint configuration (bge-base-en-v1.5 at 768-dim by default)"
}

variable "vector_dimension" {
  type        = number
  description = "S3 Vectors index dimension (must match the KB embedding model output)"
  default     = 1024
}
