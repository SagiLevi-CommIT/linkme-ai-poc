locals {
  global_vars = read_terragrunt_config(find_in_parent_folders("global.hcl")).locals
  account_id  = local.global_vars.commit_ai_sandbox_01_account_id
}
