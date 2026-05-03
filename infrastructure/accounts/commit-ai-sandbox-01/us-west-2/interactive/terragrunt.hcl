include "base" {
  path = find_in_parent_folders("terragrunt_base.hcl")
}

include "layer" {
  path = "${get_repo_root()}/infrastructure/layers/interactive/_include.hcl"
}
