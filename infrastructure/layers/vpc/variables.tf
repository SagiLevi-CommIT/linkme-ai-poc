variable "account_id" {
  type        = string
  description = "AWS account ID - used in allowed_account_ids provider constraint"
}

variable "az_count" {
  type        = number
  description = "Number of Availability Zones to use - AZs are auto-discovered from the region"
  default     = 2
  validation {
    condition     = var.az_count == 2
    error_message = "Only 2 AZs are currently supported. 3-AZ requires additional subnet variables and resources."
  }
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "KMS key ARN for CloudWatch log group encryption - leave null to use AWS-managed encryption"
  default     = null
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
  description = "Project name used in resource naming and log group paths"
}

variable "region" {
  type        = string
  description = "AWS region - used in VPC endpoint service names"
}

variable "subnet_cidr_private_app_1" {
  type        = string
  description = "CIDR block for private application subnet in AZ1"
}

variable "subnet_cidr_private_app_2" {
  type        = string
  description = "CIDR block for private application subnet in AZ2"
}

variable "subnet_cidr_private_db_1" {
  type        = string
  description = "CIDR block for private database subnet in AZ1"
}

variable "subnet_cidr_private_db_2" {
  type        = string
  description = "CIDR block for private database subnet in AZ2"
}

variable "subnet_cidr_public_1" {
  type        = string
  description = "CIDR block for public subnet in AZ1"
}

variable "subnet_cidr_public_2" {
  type        = string
  description = "CIDR block for public subnet in AZ2"
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC"
}
