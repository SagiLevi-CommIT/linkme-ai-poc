# Layer: cicd

Deploys the CI/CD infrastructure for the LinkMe AI AgentCore POC: CodeBuild project for the backend agent, IAM role, S3 artifacts bucket, and CloudWatch log group.

The layer is driven by the `codebuild_projects` map in `region.hcl`. Only the `backend` project is enabled in this POC (`enable_frontend = false`).

## Resources created

| Category | Resources |
|---|---|
| S3 | `linkme-ai-poc-codebuild-artifacts-<account_id>` (versioned, AES256, BucketOwnerEnforced) |
| IAM | `role-poc-codebuild-backend` with scoped ECR push and AgentCore policies |
| CodeBuild | `linkme-ai-poc-backend-build` (ARM64, ARM_CONTAINER) |
| CloudWatch | `/aws/codebuild/linkme-ai-poc-backend-build` log group |

## Build pipeline

| Project | Architecture | Buildspec | What it does |
|---|---|---|---|
| `linkme-ai-poc-backend-build` | ARM64 — `BUILD_GENERAL1_LARGE` | `agentcore-be/buildspec.yml` | Build + push ARM64 agent image; create/update AgentCore Runtime; wait for READY |

## CodeBuild environment variables injected

| Variable | Source |
|---|---|
| `ECR_REPOSITORY_URI` | Backend ECR URI from `app` layer (auto-injected via `ecr_repo_key`) |
| `AGENTCORE_RUNTIME_NAME` | Derived from project/env name |
| `AGENTCORE_EXECUTION_ROLE_ARN` | AgentCore role ARN from `app` layer |
| `AGENTCORE_SECURITY_GROUP` | AgentCore SG ID from `app` layer |
| `AGENTCORE_SUBNET_1/2` | Private app subnet IDs from `vpc` layer |

## Dependencies

- `vpc` — `private_app_subnet_1_id`, `private_app_subnet_2_id`
- `app` — ECR URIs/ARNs, backend IAM role ARN, backend security group ID

---

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | ~> 6.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_aws"></a> [aws](#provider\_aws) | ~> 6.0 |

## Modules

No modules.

## Resources

| Name | Type |
|------|------|
| [aws_cloudwatch_log_group.codebuild](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_codebuild_project.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/codebuild_project) | resource |
| [aws_iam_role.codebuild](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.codebuild_base](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.codebuild_ecr](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.codebuild_extra](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_s3_bucket.access_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket.artifacts](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket_lifecycle_configuration.access_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_lifecycle_configuration) | resource |
| [aws_s3_bucket_lifecycle_configuration.artifacts](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_lifecycle_configuration) | resource |
| [aws_s3_bucket_logging.artifacts](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_logging) | resource |
| [aws_s3_bucket_ownership_controls.access_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_ownership_controls) | resource |
| [aws_s3_bucket_ownership_controls.artifacts](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_ownership_controls) | resource |
| [aws_s3_bucket_policy.access_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_policy) | resource |
| [aws_s3_bucket_policy.artifacts](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_policy) | resource |
| [aws_s3_bucket_public_access_block.access_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_public_access_block.artifacts](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.access_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.artifacts](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_versioning.access_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning) | resource |
| [aws_s3_bucket_versioning.artifacts](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning) | resource |
| [aws_iam_policy_document.access_logs_bucket_policy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.artifacts_ssl_only](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.codebuild_assume](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_account_id"></a> [account\_id](#input\_account\_id) | AWS account ID — used in allowed\_account\_ids provider constraint and IAM policy ARNs | `string` | n/a | yes |
| <a name="input_cloudwatch_kms_key_arn"></a> [cloudwatch\_kms\_key\_arn](#input\_cloudwatch\_kms\_key\_arn) | KMS key ARN for CloudWatch log group encryption — leave null to use AWS-managed encryption | `string` | `null` | no |
| <a name="input_codebuild_extra_env_vars"></a> [codebuild\_extra\_env\_vars](#input\_codebuild\_extra\_env\_vars) | Map of project key to additional environment variables for each CodeBuild project | `map(map(string))` | `{}` | no |
| <a name="input_codebuild_extra_iam_policies"></a> [codebuild\_extra\_iam\_policies](#input\_codebuild\_extra\_iam\_policies) | Map of project key to additional IAM policy JSON for each CodeBuild role | `map(string)` | `{}` | no |
| <a name="input_codebuild_pass_role_arns"></a> [codebuild\_pass\_role\_arns](#input\_codebuild\_pass\_role\_arns) | Specific IAM role ARNs CodeBuild may pass to ECS tasks and AgentCore — replaces project-name wildcard | `list(string)` | `[]` | no |
| <a name="input_codebuild_projects"></a> [codebuild\_projects](#input\_codebuild\_projects) | Map of project key to CodeBuild project configuration | <pre>map(object({<br>    description      = string<br>    buildspec        = string<br>    compute_type     = string<br>    environment_type = string<br>    image            = string<br>    ecr_repo_key     = optional(string)<br>    privileged_mode  = optional(bool, false)<br>  }))</pre> | n/a | yes |
| <a name="input_codecommit_repo_name"></a> [codecommit\_repo\_name](#input\_codecommit\_repo\_name) | Name of the CodeCommit repository used as CodeBuild source | `string` | n/a | yes |
| <a name="input_ecr_repository_arns"></a> [ecr\_repository\_arns](#input\_ecr\_repository\_arns) | Map of ECR repo key to ARN — from app layer | `map(string)` | `{}` | no |
| <a name="input_ecr_repository_uris"></a> [ecr\_repository\_uris](#input\_ecr\_repository\_uris) | Map of ECR repo key to URI — from app layer | `map(string)` | `{}` | no |
| <a name="input_env"></a> [env](#input\_env) | Environment short name (e.g. poc, dev, prod) | `string` | n/a | yes |
| <a name="input_env_type"></a> [env\_type](#input\_env\_type) | Environment type for behavior toggles | `string` | n/a | yes |
| <a name="input_log_retention_days"></a> [log\_retention\_days](#input\_log\_retention\_days) | CloudWatch log retention in days — 7 for POC, 90 for nonprod, 365 for prod | `number` | `7` | no |
| <a name="input_project_name"></a> [project\_name](#input\_project\_name) | Project name used in resource naming | `string` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | AWS region — passed as CodeBuild AWS\_DEFAULT\_REGION env var | `string` | n/a | yes |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_artifacts_bucket_name"></a> [artifacts\_bucket\_name](#output\_artifacts\_bucket\_name) | Name of the S3 bucket used for CodeBuild build artifacts |
| <a name="output_codebuild_project_names"></a> [codebuild\_project\_names](#output\_codebuild\_project\_names) | Map of project key to CodeBuild project name |
| <a name="output_codebuild_role_arns"></a> [codebuild\_role\_arns](#output\_codebuild\_role\_arns) | Map of project key to CodeBuild IAM role ARN |
<!-- END_TF_DOCS -->
