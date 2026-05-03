terraform {
  source = "${get_repo_root()}/infrastructure/layers/messaging//"
}

locals {
  region_vars = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals
}

dependency "vpc" {
  config_path = "../vpc"

  mock_outputs = {
    vpc_id                 = "vpc-00000000000000000"
    vpc_cidr               = "10.143.32.0/20"
    private_app_subnet_ids = ["subnet-00000000000000000", "subnet-00000000000000001"]
    private_db_subnet_ids  = ["subnet-00000000000000002", "subnet-00000000000000003"]
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

inputs = {
  region                 = local.region_vars.aws_region
  vpc_id                 = dependency.vpc.outputs.vpc_id
  private_app_subnet_ids = dependency.vpc.outputs.private_app_subnet_ids
  private_db_subnet_ids  = dependency.vpc.outputs.private_db_subnet_ids
}
