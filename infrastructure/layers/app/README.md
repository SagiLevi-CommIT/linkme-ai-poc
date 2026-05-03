# Layer: app

Deploys the application infrastructure for the LinkMe AI AgentCore POC: ECR repositories, security groups, IAM roles, ECS cluster, backend role, and CloudWatch log group.

The layer is driven by feature flags in `region.hcl`. In this POC: `enable_frontend = false` (no ALB, ECS task/service, or frontend security group) and `backend_type = "agentcore"` (AgentCore runtime, not ECS/Lambda backend).

## Resources created

| Category | Resources |
|---|---|
| ECR | `backend`, `ai-msg-processor`, `ai-service`, `instagram-mock`, `publisher-mock` (IMMUTABLE tags, KMS encrypted, scan on push) |
| KMS | Shared KMS key + alias for ECR encryption |
| Security Groups | `sgr-<project>-<env>-backend` (AgentCore; standalone ingress/egress rules) |
| IAM | `role-<project>-<env>-ecs-execution`, `role-<project>-<env>-backend` with scoped inline policies |
| ECS | ECS cluster (Fargate + Fargate Spot, Container Insights enabled) |
| CloudWatch | `/aws/agentcore/<project>-<env>-backend` log group |

**Disabled in this POC** (`enable_frontend = false`): ALB, ECS security group, ECS task role, ECS task definition + service, frontend target group, WAF.

## Dependencies

- `vpc` — `vpc_id`, `private_app_subnet_1_id`, `private_app_subnet_2_id`

## Consumed by

- `cicd` — ECR URIs/ARNs, backend IAM role ARN, backend security group ID
- `ai` — backend IAM role ARN (for KB/Bedrock policies)

## Security notes

- ALB is disabled in this POC; set `enable_frontend = true` and `certificate_arn` to enable HTTPS
- All egress rules use `0.0.0.0/0` (required to reach Bedrock, ECR, and S3 endpoints)
- ECR repos use KMS CMK encryption and immutable tags

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
| [aws_cloudwatch_log_group.backend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_log_group.frontend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_ecr_lifecycle_policy.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecr_lifecycle_policy) | resource |
| [aws_ecr_registry_scanning_configuration.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecr_registry_scanning_configuration) | resource |
| [aws_ecr_repository.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecr_repository) | resource |
| [aws_ecr_repository_policy.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecr_repository_policy) | resource |
| [aws_ecs_cluster.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_cluster) | resource |
| [aws_ecs_cluster_capacity_providers.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_cluster_capacity_providers) | resource |
| [aws_ecs_service.backend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_service) | resource |
| [aws_ecs_task_definition.backend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_task_definition) | resource |
| [aws_iam_role.backend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.ecs_execution](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.ecs_task](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.backend_bedrock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.backend_cloudwatch](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.backend_ecr](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.backend_knowledge_base](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.backend_s3](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.ecs_task_agentcore](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.ecs_task_cloudwatch](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.ecs_task_lambda_invoke](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy_attachment.backend_lambda_vpc](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_iam_role_policy_attachment.ecs_execution_managed](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_kms_alias.ecr](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_alias) | resource |
| [aws_kms_key.ecr](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_key) | resource |
| [aws_lambda_function.backend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_function) | resource |
| [aws_lb.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lb) | resource |
| [aws_lb_listener.http](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lb_listener) | resource |
| [aws_lb_listener.https](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lb_listener) | resource |
| [aws_lb_target_group.frontend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lb_target_group) | resource |
| [aws_security_group.alb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_security_group.backend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_security_group.ecs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_vpc_security_group_egress_rule.alb_all](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_egress_rule) | resource |
| [aws_vpc_security_group_egress_rule.backend_all](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_egress_rule) | resource |
| [aws_vpc_security_group_egress_rule.ecs_all](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_egress_rule) | resource |
| [aws_vpc_security_group_ingress_rule.alb_http](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_ingress_rule) | resource |
| [aws_vpc_security_group_ingress_rule.alb_https](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_ingress_rule) | resource |
| [aws_vpc_security_group_ingress_rule.backend_from_frontend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_ingress_rule) | resource |
| [aws_vpc_security_group_ingress_rule.ecs_app](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_ingress_rule) | resource |
| [aws_wafv2_web_acl.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/wafv2_web_acl) | resource |
| [aws_wafv2_web_acl_association.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/wafv2_web_acl_association) | resource |
| [aws_iam_policy_document.backend_assume](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.ecr_kms](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.ecr_push](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.ecs_assume](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_account_id"></a> [account\_id](#input\_account\_id) | AWS account ID — used in allowed\_account\_ids provider constraint and IAM policy ARNs | `string` | n/a | yes |
| <a name="input_alb_access_logs_bucket"></a> [alb\_access\_logs\_bucket](#input\_alb\_access\_logs\_bucket) | S3 bucket name for ALB access logs — leave empty to disable | `string` | `""` | no |
| <a name="input_app_container_port"></a> [app\_container\_port](#input\_app\_container\_port) | Container port the frontend application listens on | `number` | `8501` | no |
| <a name="input_backend_container_port"></a> [backend\_container\_port](#input\_backend\_container\_port) | Port the backend listens on — used for security group rules | `number` | `8080` | no |
| <a name="input_backend_ecs_config"></a> [backend\_ecs\_config](#input\_backend\_ecs\_config) | ECS backend configuration — only used when backend\_type is ecs | <pre>object({<br>    cpu           = optional(number, 512)<br>    memory        = optional(number, 1024)<br>    desired_count = optional(number, 0)<br>    image_tag     = optional(string, "latest")<br>    ecr_repo_key  = optional(string, "backend")<br>  })</pre> | `{}` | no |
| <a name="input_backend_lambda_config"></a> [backend\_lambda\_config](#input\_backend\_lambda\_config) | Lambda backend configuration — only used when backend\_type is lambda. Default architecture is arm64 to match the ARM\_CONTAINER CodeBuild image. | <pre>object({<br>    architectures = optional(list(string), ["arm64"])<br>    ecr_repo_key  = optional(string, "backend")<br>    image_tag     = optional(string, "latest")<br>    memory_size   = optional(number, 512)<br>    timeout       = optional(number, 30)<br>  })</pre> | `{}` | no |
| <a name="input_backend_type"></a> [backend\_type](#input\_backend\_type) | Backend compute type: agentcore (Bedrock AgentCore), ecs (Fargate service), lambda (Lambda function), or none | `string` | `"none"` | no |
| <a name="input_bedrock_model_arns"></a> [bedrock\_model\_arns](#input\_bedrock\_model\_arns) | List of Bedrock foundation model ARNs the backend role may invoke — leave empty to skip Bedrock policy | `list(string)` | `[]` | no |
| <a name="input_certificate_arn"></a> [certificate\_arn](#input\_certificate\_arn) | ACM certificate ARN for HTTPS listener — leave empty to use HTTP only | `string` | `""` | no |
| <a name="input_cloudwatch_kms_key_arn"></a> [cloudwatch\_kms\_key\_arn](#input\_cloudwatch\_kms\_key\_arn) | KMS key ARN for CloudWatch log group encryption — leave null to use AWS-managed encryption | `string` | `null` | no |
| <a name="input_ecr_push_role_arns"></a> [ecr\_push\_role\_arns](#input\_ecr\_push\_role\_arns) | Map of ECR repo key to IAM role ARN allowed to push images — set after cicd layer deploy | `map(string)` | `{}` | no |
| <a name="input_ecr_repositories"></a> [ecr\_repositories](#input\_ecr\_repositories) | Map of repository key to description — one ECR repo created per entry | `map(string)` | <pre>{<br>  "backend": "Backend application image",<br>  "frontend": "Frontend application image"<br>}</pre> | no |
| <a name="input_enable_alb_deletion_protection"></a> [enable\_alb\_deletion\_protection](#input\_enable\_alb\_deletion\_protection) | Enable ALB deletion protection — set true for production | `bool` | `false` | no |
| <a name="input_enable_bedrock_knowledge_base"></a> [enable\_bedrock\_knowledge\_base](#input\_enable\_bedrock\_knowledge\_base) | Grant the backend role access to Bedrock Knowledge Bases | `bool` | `false` | no |
| <a name="input_enable_frontend"></a> [enable\_frontend](#input\_enable\_frontend) | Deploy frontend infrastructure (ALB, target group, ECS frontend SG, task role, log group) — set false when no frontend is needed | `bool` | `true` | no |
| <a name="input_enable_waf"></a> [enable\_waf](#input\_enable\_waf) | Attach a WAFv2 WebACL with AWS managed rules to the ALB — set true for production | `bool` | `false` | no |
| <a name="input_env"></a> [env](#input\_env) | Environment short name (e.g. poc, dev, prod) | `string` | n/a | yes |
| <a name="input_env_type"></a> [env\_type](#input\_env\_type) | Environment type for behavior toggles | `string` | n/a | yes |
| <a name="input_kms_admin_role_arns"></a> [kms\_admin\_role\_arns](#input\_kms\_admin\_role\_arns) | IAM role ARNs granted KMS key administration rights — account root is always retained as break-glass | `list(string)` | `[]` | no |
| <a name="input_log_retention_days"></a> [log\_retention\_days](#input\_log\_retention\_days) | CloudWatch log retention in days — 7 for POC, 90 for nonprod, 365 for prod | `number` | `7` | no |
| <a name="input_private_app_subnet_ids"></a> [private\_app\_subnet\_ids](#input\_private\_app\_subnet\_ids) | List of private application subnet IDs — used for ECS backend and Lambda VPC config | `list(string)` | `[]` | no |
| <a name="input_project_name"></a> [project\_name](#input\_project\_name) | Project name used in resource naming | `string` | n/a | yes |
| <a name="input_public_subnet_1_id"></a> [public\_subnet\_1\_id](#input\_public\_subnet\_1\_id) | ID of public subnet in AZ1 — from vpc layer, used for ALB | `string` | n/a | yes |
| <a name="input_public_subnet_2_id"></a> [public\_subnet\_2\_id](#input\_public\_subnet\_2\_id) | ID of public subnet in AZ2 — from vpc layer, used for ALB | `string` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | AWS region — used in IAM policy ARNs | `string` | n/a | yes |
| <a name="input_s3_data_buckets"></a> [s3\_data\_buckets](#input\_s3\_data\_buckets) | Map of logical name to S3 bucket name for backend data access IAM policies | `map(string)` | `{}` | no |
| <a name="input_vpc_id"></a> [vpc\_id](#input\_vpc\_id) | ID of the VPC — from vpc layer | `string` | n/a | yes |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_alb_dns_name"></a> [alb\_dns\_name](#output\_alb\_dns\_name) | DNS name of the Application Load Balancer — empty when enable\_frontend is false |
| <a name="output_alb_listener_arn"></a> [alb\_listener\_arn](#output\_alb\_listener\_arn) | ARN of the HTTP ALB listener — empty when enable\_frontend is false |
| <a name="output_alb_url"></a> [alb\_url](#output\_alb\_url) | HTTP URL of the Application Load Balancer — empty when enable\_frontend is false |
| <a name="output_backend_ecs_service_name"></a> [backend\_ecs\_service\_name](#output\_backend\_ecs\_service\_name) | Name of the backend ECS service — empty when backend\_type is not ecs |
| <a name="output_backend_lambda_function_arn"></a> [backend\_lambda\_function\_arn](#output\_backend\_lambda\_function\_arn) | ARN of the backend Lambda function — empty when backend\_type is not lambda |
| <a name="output_backend_lambda_function_name"></a> [backend\_lambda\_function\_name](#output\_backend\_lambda\_function\_name) | Name of the backend Lambda function — empty when backend\_type is not lambda |
| <a name="output_backend_log_group_name"></a> [backend\_log\_group\_name](#output\_backend\_log\_group\_name) | Name of the backend CloudWatch log group — empty when no backend |
| <a name="output_backend_role_arn"></a> [backend\_role\_arn](#output\_backend\_role\_arn) | ARN of the backend IAM role — empty when backend\_type is none |
| <a name="output_backend_security_group_id"></a> [backend\_security\_group\_id](#output\_backend\_security\_group\_id) | ID of the backend security group — empty when backend\_type is none |
| <a name="output_ecr_repository_arns"></a> [ecr\_repository\_arns](#output\_ecr\_repository\_arns) | Map of ECR repository key to ARN |
| <a name="output_ecr_repository_names"></a> [ecr\_repository\_names](#output\_ecr\_repository\_names) | Map of ECR repository key to name |
| <a name="output_ecr_repository_uris"></a> [ecr\_repository\_uris](#output\_ecr\_repository\_uris) | Map of ECR repository key to URI |
| <a name="output_ecs_cluster_arn"></a> [ecs\_cluster\_arn](#output\_ecs\_cluster\_arn) | ARN of the ECS cluster |
| <a name="output_ecs_cluster_name"></a> [ecs\_cluster\_name](#output\_ecs\_cluster\_name) | Name of the ECS cluster |
| <a name="output_ecs_security_group_id"></a> [ecs\_security\_group\_id](#output\_ecs\_security\_group\_id) | ID of the ECS frontend tasks security group — empty when enable\_frontend is false |
| <a name="output_ecs_task_execution_role_arn"></a> [ecs\_task\_execution\_role\_arn](#output\_ecs\_task\_execution\_role\_arn) | ARN of the ECS task execution IAM role |
| <a name="output_ecs_task_role_arn"></a> [ecs\_task\_role\_arn](#output\_ecs\_task\_role\_arn) | ARN of the ECS frontend task IAM role — empty when enable\_frontend is false |
| <a name="output_frontend_target_group_arn"></a> [frontend\_target\_group\_arn](#output\_frontend\_target\_group\_arn) | ARN of the frontend ALB target group — empty when enable\_frontend is false |
<!-- END_TF_DOCS -->
