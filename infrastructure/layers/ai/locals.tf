locals {
  env        = var.env
  name_fmt   = "%s-${var.project_name}-${local.env}-%s"
  name_short = "%s-${var.project_name}-${local.env}"

  enable_knowledge_base = var.enable_knowledge_base
  enable_agent          = var.enable_agent
  enable_sagemaker      = var.enable_sagemaker

  vector_bucket_name = "${var.project_name}-${var.env}-kb-vectors"
}

