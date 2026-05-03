terraform {
  source = "${get_repo_root()}/infrastructure/layers/vpc//"
}

locals {
  region_vars = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals
}

inputs = {
  region = local.region_vars.aws_region
}
