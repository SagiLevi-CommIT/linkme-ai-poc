locals {
  env = var.env
  # tflint-ignore: terraform_unused_declarations
  is_prod = var.env_type == "prod"

  # Name helper: format(local.name_fmt, "<prefix>", "<descriptive-name>")
  # Produces: "<prefix>-<project>-<env>-<descriptive-name>" (e.g., "role-linkme-ai-poc-codebuild-frontend")
  name_fmt = "%s-${var.project_name}-${local.env}-%s"
  # tflint-ignore: terraform_unused_declarations
  name_short = "%s-${var.project_name}-${local.env}"

  # CodeBuild projects that push to ECR (have an ecr_repo_key)
  codebuild_ecr_projects = {
    for k, v in var.codebuild_projects : k => v if v.ecr_repo_key != null
  }

  # Auto-trigger path map: source-path-prefix -> CodeBuild project name.
  # Only projects whose buildspec lives under a subdirectory of src/ get a
  # path-filter entry; projects with a root buildspec (e.g. backend,
  # agentcore) are not auto-triggered and must be started manually.
  codebuild_auto_trigger_map = {
    for k, v in var.codebuild_projects :
    "${dirname(v.buildspec)}/" => "${var.project_name}-${var.env}-${k}-build"
    if length(split("/", v.buildspec)) > 1 && startswith(v.buildspec, "src/")
  }
}
