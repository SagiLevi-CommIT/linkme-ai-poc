terraform {
  source = "${get_repo_root()}/infrastructure/layers/app//"
}

locals {
  region_vars = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals
}

dependency "vpc" {
  config_path = "../vpc"

  mock_outputs = {
    nat_gateway_id          = "nat-00000000000000000"
    private_app_subnet_ids  = ["subnet-00000000000000000", "subnet-00000000000000001"]
    private_app_subnet_1_id = "subnet-00000000000000000"
    private_app_subnet_2_id = "subnet-00000000000000001"
    private_db_subnet_ids   = ["subnet-00000000000000002", "subnet-00000000000000003"]
    private_db_subnet_1_id  = "subnet-00000000000000002"
    private_db_subnet_2_id  = "subnet-00000000000000003"
    public_subnet_ids       = ["subnet-00000000000000004", "subnet-00000000000000005"]
    public_subnet_1_id      = "subnet-00000000000000004"
    public_subnet_2_id      = "subnet-00000000000000005"
    vpc_cidr                = "10.142.16.0/20"
    vpc_id                  = "vpc-00000000000000000"
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "destroy", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
}

# Dependency outputs and variable name mappings not covered by base config merge
inputs = {
  vpc_id                 = dependency.vpc.outputs.vpc_id
  public_subnet_1_id     = dependency.vpc.outputs.public_subnet_1_id
  public_subnet_2_id     = dependency.vpc.outputs.public_subnet_2_id
  private_app_subnet_ids = dependency.vpc.outputs.private_app_subnet_ids
  region                 = local.region_vars.aws_region
}
