variable "account_id" {
  type        = string
  description = "AWS account ID - used in allowed_account_ids provider constraint and IAM policy ARNs"
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "KMS key ARN for CloudWatch log group encryption - leave null to use AWS-managed encryption"
  default     = null
}

variable "codebuild_extra_env_vars" {
  type        = map(map(string))
  description = "Map of project key to additional environment variables for each CodeBuild project"
  default     = {}
}

variable "codebuild_extra_iam_policies" {
  type        = map(string)
  description = "Map of project key to additional IAM policy JSON for each CodeBuild role"
  default     = {}
}

variable "codebuild_pass_role_arns" {
  type        = list(string)
  description = "Specific IAM role ARNs CodeBuild may pass to ECS tasks and AgentCore - replaces project-name wildcard"
  default     = []
}

variable "codebuild_dispatcher_source_dir" {
  type        = string
  description = "Absolute filesystem path to the CodeCommit to CodeBuild dispatcher Lambda source (resolved via get_repo_root in terragrunt)"
  default     = null
}

variable "codebuild_source_version" {
  type        = string
  description = "CodeCommit branch ref used as the build source (e.g. refs/heads/ai_impl)"
  default     = "refs/heads/main"
}

variable "codebuild_projects" {
  type = map(object({
    description      = string
    buildspec        = string
    compute_type     = string
    environment_type = string
    image            = string
    ecr_repo_key     = optional(string)
    privileged_mode  = optional(bool, false)
  }))
  description = "Map of project key to CodeBuild project configuration"
}

variable "codecommit_repo_name" {
  type        = string
  description = "Name of the CodeCommit repository used as CodeBuild source"
}

variable "ecr_repository_arns" {
  type        = map(string)
  description = "Map of ECR repo key to ARN - from app layer"
  default     = {}
}

variable "ecr_repository_uris" {
  type        = map(string)
  description = "Map of ECR repo key to URI - from app layer"
  default     = {}
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

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention in days - 7 for POC, 90 for nonprod, 365 for prod"
  default     = 7
}

variable "project_name" {
  type        = string
  description = "Project name used in resource naming"
}

variable "region" {
  type        = string
  description = "AWS region - passed as CodeBuild AWS_DEFAULT_REGION env var"
}
