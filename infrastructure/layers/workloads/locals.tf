locals {
  env      = var.env
  name_fmt = "%s-${local.env}-%s"
}
