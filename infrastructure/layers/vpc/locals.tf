locals {
  env = var.env
  # tflint-ignore: terraform_unused_declarations
  is_prod = var.env_type == "prod"

  # Name helper: format(local.name_fmt, "<prefix>", "<descriptive-name>")
  # Produces: "<prefix>-<project>-<env>-<descriptive-name>" (e.g., "vpc-linkme-ai-poc")
  name_fmt   = "%s-${var.project_name}-${local.env}-%s"
  name_short = "%s-${var.project_name}-${local.env}"

  # Select the first N available AZs in the region
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)
}
