variable "account_id" {
  type        = string
  description = "AWS account ID - used in allowed_account_ids provider constraint and IAM policy ARNs"
}

variable "alb_access_logs_bucket" {
  type        = string
  description = "S3 bucket name for ALB access logs - leave empty to disable"
  default     = ""
}

variable "app_container_port" {
  type        = number
  description = "Container port the frontend application listens on"
  default     = 8501
}

variable "backend_container_port" {
  type        = number
  description = "Port the backend listens on - used for security group rules"
  default     = 8080
}

variable "backend_ecs_config" {
  type = object({
    cpu           = optional(number, 512)
    memory        = optional(number, 1024)
    desired_count = optional(number, 0)
    image_tag     = optional(string, "latest")
    ecr_repo_key  = optional(string, "backend")
  })
  description = "ECS backend configuration - only used when backend_type is ecs"
  default     = {}
}

variable "backend_lambda_config" {
  type = object({
    architectures = optional(list(string), ["arm64"])
    ecr_repo_key  = optional(string, "backend")
    image_tag     = optional(string, "latest")
    memory_size   = optional(number, 512)
    timeout       = optional(number, 30)
  })
  description = "Lambda backend configuration - only used when backend_type is lambda. Default architecture is arm64 to match the ARM_CONTAINER CodeBuild image."
  default     = {}
}

variable "backend_type" {
  type        = string
  description = "Backend compute type: agentcore (Bedrock AgentCore), ecs (Fargate service), lambda (Lambda function), or none"
  default     = "none"
  validation {
    condition     = contains(["agentcore", "ecs", "lambda", "none"], var.backend_type)
    error_message = "Must be agentcore, ecs, lambda, or none."
  }
}

variable "bedrock_model_arns" {
  type        = list(string)
  description = "List of Bedrock foundation model ARNs the backend role may invoke - leave empty to skip Bedrock policy"
  default     = []
}

variable "certificate_arn" {
  type        = string
  description = "ACM certificate ARN for HTTPS listener - leave empty to use HTTP only"
  default     = ""
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "KMS key ARN for CloudWatch log group encryption - leave null to use AWS-managed encryption"
  default     = null
}

variable "ecr_push_role_arns" {
  type        = map(string)
  description = "Map of ECR repo key to IAM role ARN allowed to push images - set after cicd layer deploy"
  default     = {}
}

variable "ecr_repositories" {
  type        = map(string)
  description = "Map of repository key to description - one ECR repo created per entry. Overridden by region.hcl."
  default     = {}
}

variable "enable_alb_deletion_protection" {
  type        = bool
  description = "Enable ALB deletion protection - set true for production"
  default     = false
}

variable "enable_bedrock_knowledge_base" {
  type        = bool
  description = "Grant the backend role access to Bedrock Knowledge Bases"
  default     = false
}

variable "enable_frontend" {
  type        = bool
  description = "Deploy frontend infrastructure (ALB, target group, ECS frontend SG, task role, log group) - set false when no frontend is needed"
  default     = true
}

variable "enable_waf" {
  type        = bool
  description = "Attach a WAFv2 WebACL with AWS managed rules to the ALB - set true for production"
  default     = false
}

variable "env" {
  type        = string
  description = "Environment short name (e.g. poc, dev, prod)"
}

variable "env_type" {
  type        = string
  description = "Environment type for behavior toggles"
  validation {
    condition     = contains(["prod", "nonprod", "poc"], var.env_type)
    error_message = "Must be prod, nonprod, or poc."
  }
}

variable "kms_admin_role_arns" {
  type        = list(string)
  description = "IAM role ARNs granted KMS key administration rights - account root is always retained as break-glass"
  default     = []
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention in days - 7 for POC, 90 for nonprod, 365 for prod"
  default     = 7
}

variable "private_app_subnet_ids" {
  type        = list(string)
  description = "List of private application subnet IDs - used for ECS backend and Lambda VPC config"
  default     = []
}

variable "project_name" {
  type        = string
  description = "Project name used in resource naming"
}

variable "public_subnet_1_id" {
  type        = string
  description = "ID of public subnet in AZ1 - from vpc layer, used for ALB"
}

variable "public_subnet_2_id" {
  type        = string
  description = "ID of public subnet in AZ2 - from vpc layer, used for ALB"
}

variable "region" {
  type        = string
  description = "AWS region - used in IAM policy ARNs"
}

variable "s3_data_buckets" {
  type        = map(string)
  description = "Map of logical name to S3 bucket name for backend data access IAM policies"
  default     = {}
}

variable "vpc_id" {
  type        = string
  description = "ID of the VPC - from vpc layer"
}
