locals {
  env      = var.env
  name_fmt = "%s-${local.env}-%s"

  agentcore_image_uri = "${var.agentcore_ecr_repository_url}:latest"
}
