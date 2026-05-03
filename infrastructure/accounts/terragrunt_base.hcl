locals {
  global_vars  = read_terragrunt_config(find_in_parent_folders("global.hcl")).locals
  account_vars = read_terragrunt_config(find_in_parent_folders("account.hcl")).locals
  region_vars  = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals
  env          = local.region_vars.env
  region       = local.region_vars.aws_region
  env_type     = local.region_vars.env_type
  layer        = basename(get_original_terragrunt_dir())
  account      = split("/", path_relative_to_include())[0]
  account_id   = local.account_vars.account_id

  aws_profile = local.account

  default_tags = merge(
    lookup(local.global_vars, "default_tags", {}),
    lookup(local.account_vars, "default_tags", {}),
    lookup(local.region_vars, "default_tags", {}),
    {
      environment-name = local.env
      environment-type = local.env_type
      created-by       = "terraform"
      managed-by       = "terraform"
      layer            = local.layer
    }
  )
}

terraform_version_constraint  = ">= 1.13.0, < 2.0.0"
terragrunt_version_constraint = ">= 0.90.0, < 1.0.0"

terraform {
  # Terragrunt's runner pool does not trigger S3 bucket auto-creation.
  # This hook creates the bucket before terraform init runs on every unit.
  before_hook "ensure_state_bucket" {
    commands = ["init"]
    execute = [
      "${get_repo_root()}/infrastructure/scripts/ensure-state-bucket.sh",
      format("terraform-states-%s-%s", local.account_id, local.region),
      local.region,
    ]
  }

  before_hook "tflint" {
    commands = ["plan", "apply"]
    execute  = ["${get_repo_root()}/infrastructure/scripts/tflint-hook.sh", "${get_repo_root()}/.tflint.hcl"]
  }

  extra_arguments "aws_provider_config" {
    commands = [get_terraform_command()]
    env_vars = merge(
      {
        AWS_PROFILE = local.aws_profile
        AWS_REGION  = local.region
      },
      { for k, v in local.default_tags : "TF_AWS_DEFAULT_TAGS_${k}" => v }
    )
  }

  extra_arguments "retry_lock" {
    commands  = get_terraform_commands_that_need_locking()
    arguments = ["-lock-timeout=5m"]
  }
}

remote_state {
  backend = "s3"
  config = {
    encrypt      = true
    region       = local.region
    profile      = local.aws_profile
    key          = format("%s/terraform.tfstate", path_relative_to_include())
    bucket       = format("terraform-states-%s-%s", local.account_id, local.region)
    use_lockfile = true
  }
  generate = {
    path      = "_backend.tf"
    if_exists = "overwrite"
  }
}

download_dir = "${get_repo_root()}/.terragrunt-cache/${get_path_from_repo_root()}"

inputs = merge(
  local.global_vars,
  local.account_vars,
  local.region_vars,
)
