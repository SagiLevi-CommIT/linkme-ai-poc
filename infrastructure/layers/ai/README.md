# Layer: ai

Deploys the AI infrastructure for the LinkMe AI POC: Bedrock Knowledge Base with S3 Vectors storage, Bedrock Agent, and data preprocessor Lambda.

## Resources created

| Category | Condition | Resources |
|---|---|---|
| S3 | always | KB data bucket (versioned, AES256, BucketOwnerEnforced) |
| S3 Vectors | `enable_knowledge_base` | Vector bucket + index (float32, 1024 dim, cosine) |
| Bedrock KB | `enable_knowledge_base` | Knowledge Base + S3 data source |
| Bedrock Agent | `enable_agent` | Agent + alias (`live`) + KB association |
| IAM | per feature | KB role, Agent role, Preprocessor role with scoped policies |
| Lambda | `enable_preprocessor` | Preprocessor function, CloudWatch logs, VPC security group |

## Feature flags

| Flag | Default | Purpose |
|---|---|---|
| `enable_knowledge_base` | `true` | Bedrock KB + S3 Vectors (no AOSS cost) |
| `enable_agent` | `true` | Bedrock Agent with configurable instruction |
| `enable_preprocessor` | `false` | Lambda for PDF/image/video processing (needs app code) |

## Dependencies

- `vpc` — `vpc_id`, `private_app_subnet_ids` (for Lambda VPC config)

## Operator workflow

The SageMaker endpoint is billed per running instance, so the POC
tears it down between tests and recreates it on demand:

```bash
task sm:down  # stops hourly billing (~30s)
task sm:up    # recreates the endpoint from the existing EndpointConfig (~5 min)
```

Model and EndpointConfig are free and always in place, so `task sm:up`
only needs to create the endpoint itself.

## Consumed by

- `app` — backend role already has wildcard KB access via `enable_bedrock_knowledge_base`
- Phase 2 services will reference `agent_id`, `knowledge_base_id` outputs

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_archive"></a> [archive](#requirement\_archive) | ~> 2.0 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | ~> 6.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_archive"></a> [archive](#provider\_archive) | ~> 2.0 |
| <a name="provider_aws"></a> [aws](#provider\_aws) | ~> 6.0 |

## Modules

No modules.

## Resources

| Name | Type |
|------|------|
| [aws_bedrockagent_agent.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_agent) | resource |
| [aws_bedrockagent_agent_alias.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_agent_alias) | resource |
| [aws_bedrockagent_agent_knowledge_base_association.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_agent_knowledge_base_association) | resource |
| [aws_bedrockagent_data_source.s3](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_data_source) | resource |
| [aws_bedrockagent_knowledge_base.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_knowledge_base) | resource |
| [aws_cloudwatch_log_group.preprocessor](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_iam_role.agent](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.kb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.preprocessor](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.agent_kb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.agent_model](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.agent_s3](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.kb_embedding](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.kb_s3_data](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.kb_s3_vectors](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.preprocessor_bedrock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.preprocessor_cloudwatch](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.preprocessor_s3](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy_attachment.preprocessor_vpc](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_lambda_function.preprocessor](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_function) | resource |
| [aws_lambda_permission.preprocessor_s3](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_permission) | resource |
| [aws_s3_bucket.kb_data](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket.kb_data_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket_logging.kb_data](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_logging) | resource |
| [aws_s3_bucket_notification.kb_data](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_notification) | resource |
| [aws_s3_bucket_ownership_controls.kb_data](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_ownership_controls) | resource |
| [aws_s3_bucket_ownership_controls.kb_data_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_ownership_controls) | resource |
| [aws_s3_bucket_policy.kb_data](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_policy) | resource |
| [aws_s3_bucket_policy.kb_data_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_policy) | resource |
| [aws_s3_bucket_public_access_block.kb_data](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_public_access_block.kb_data_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.kb_data](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.kb_data_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_versioning.kb_data](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning) | resource |
| [aws_s3_bucket_versioning.kb_data_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning) | resource |
| [aws_s3vectors_index.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3vectors_index) | resource |
| [aws_s3vectors_vector_bucket.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3vectors_vector_bucket) | resource |
| [aws_security_group.preprocessor](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_vpc_security_group_egress_rule.preprocessor_all](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_egress_rule) | resource |
| [archive_file.placeholder](https://registry.terraform.io/providers/hashicorp/archive/latest/docs/data-sources/file) | data source |
| [aws_iam_policy_document.agent_assume](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.agent_kb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.agent_model](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.agent_s3](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.kb_assume](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.kb_data_logs_policy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.kb_data_ssl_only](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.kb_embedding](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.kb_s3_data](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.kb_s3_vectors](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.preprocessor_assume](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.preprocessor_bedrock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.preprocessor_cloudwatch](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.preprocessor_s3](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_account_id"></a> [account\_id](#input\_account\_id) | AWS account ID — used in allowed\_account\_ids provider constraint and IAM policy ARNs | `string` | n/a | yes |
| <a name="input_agent_foundation_model"></a> [agent\_foundation\_model](#input\_agent\_foundation\_model) | Foundation model ID for the Bedrock Agent orchestration | `string` | `"anthropic.claude-sonnet-4-6"` | no |
| <a name="input_agent_idle_session_ttl"></a> [agent\_idle\_session\_ttl](#input\_agent\_idle\_session\_ttl) | Idle session TTL in seconds for the Bedrock Agent | `number` | `600` | no |
| <a name="input_agent_instruction"></a> [agent\_instruction](#input\_agent\_instruction) | Instructions for the Bedrock Agent — tells the agent what it should do and how to interact with users | `string` | `"You are a helpful AI assistant for the LinkMe project. You help users find and analyze information from the knowledge base. Answer questions accurately based on available data."` | no |
| <a name="input_cloudwatch_kms_key_arn"></a> [cloudwatch\_kms\_key\_arn](#input\_cloudwatch\_kms\_key\_arn) | KMS key ARN for CloudWatch log group encryption — leave null to use AWS-managed encryption | `string` | `null` | no |
| <a name="input_embedding_model_arn"></a> [embedding\_model\_arn](#input\_embedding\_model\_arn) | ARN of the embedding model for the Bedrock Knowledge Base | `string` | `"arn:aws:bedrock:us-west-2::foundation-model/amazon.titan-embed-text-v2:0"` | no |
| <a name="input_enable_agent"></a> [enable\_agent](#input\_enable\_agent) | Create the Bedrock Agent and alias | `bool` | `true` | no |
| <a name="input_enable_knowledge_base"></a> [enable\_knowledge\_base](#input\_enable\_knowledge\_base) | Create the Bedrock Knowledge Base with S3 Vectors storage | `bool` | `true` | no |
| <a name="input_enable_preprocessor"></a> [enable\_preprocessor](#input\_enable\_preprocessor) | Create the Lambda data preprocessor — requires deployment package or ECR image | `bool` | `false` | no |
| <a name="input_env"></a> [env](#input\_env) | Environment short name (e.g. poc, dev, prod) | `string` | n/a | yes |
| <a name="input_env_type"></a> [env\_type](#input\_env\_type) | Environment type for behavior toggles | `string` | n/a | yes |
| <a name="input_kb_data_bucket_name"></a> [kb\_data\_bucket\_name](#input\_kb\_data\_bucket\_name) | Override the KB data S3 bucket name — leave empty to use the default naming convention | `string` | `""` | no |
| <a name="input_log_retention_days"></a> [log\_retention\_days](#input\_log\_retention\_days) | CloudWatch log retention in days — 7 for POC, 90 for nonprod, 365 for prod | `number` | `7` | no |
| <a name="input_preprocessor_config"></a> [preprocessor\_config](#input\_preprocessor\_config) | Lambda preprocessor configuration — only used when enable\_preprocessor is true | <pre>object({<br>    runtime       = optional(string, "python3.12")<br>    handler       = optional(string, "index.handler")<br>    memory_size   = optional(number, 512)<br>    timeout       = optional(number, 300)<br>    s3_key        = optional(string, "")<br>    architectures = optional(list(string), ["arm64"])<br>  })</pre> | `{}` | no |
| <a name="input_preprocessor_nova_model_arns"></a> [preprocessor\_nova\_model\_arns](#input\_preprocessor\_nova\_model\_arns) | Nova Multimodal model ARNs the preprocessor Lambda may invoke for image/video processing | `list(string)` | <pre>[<br>  "arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0",<br>  "arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0"<br>]</pre> | no |
| <a name="input_private_app_subnet_ids"></a> [private\_app\_subnet\_ids](#input\_private\_app\_subnet\_ids) | List of private application subnet IDs — from vpc layer, used for Lambda VPC config | `list(string)` | `[]` | no |
| <a name="input_project_name"></a> [project\_name](#input\_project\_name) | Project name used in resource naming | `string` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | AWS region — used in IAM policy ARNs and resource naming | `string` | n/a | yes |
| <a name="input_vector_dimension"></a> [vector\_dimension](#input\_vector\_dimension) | Vector dimension for the S3 Vectors index — must match the embedding model output dimension | `number` | `1024` | no |
| <a name="input_vpc_id"></a> [vpc\_id](#input\_vpc\_id) | ID of the VPC — from vpc layer, used for Lambda security group | `string` | `""` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_agent_alias_id"></a> [agent\_alias\_id](#output\_agent\_alias\_id) | Alias ID of the Bedrock Agent — empty when enable\_agent is false |
| <a name="output_agent_arn"></a> [agent\_arn](#output\_agent\_arn) | ARN of the Bedrock Agent — empty when enable\_agent is false |
| <a name="output_agent_id"></a> [agent\_id](#output\_agent\_id) | ID of the Bedrock Agent — empty when enable\_agent is false |
| <a name="output_agent_role_arn"></a> [agent\_role\_arn](#output\_agent\_role\_arn) | ARN of the Bedrock Agent IAM role — empty when enable\_agent is false |
| <a name="output_kb_data_bucket_arn"></a> [kb\_data\_bucket\_arn](#output\_kb\_data\_bucket\_arn) | ARN of the KB source data S3 bucket |
| <a name="output_kb_data_bucket_name"></a> [kb\_data\_bucket\_name](#output\_kb\_data\_bucket\_name) | Name of the KB source data S3 bucket |
| <a name="output_kb_role_arn"></a> [kb\_role\_arn](#output\_kb\_role\_arn) | ARN of the Bedrock Knowledge Base IAM role — empty when enable\_knowledge\_base is false |
| <a name="output_knowledge_base_arn"></a> [knowledge\_base\_arn](#output\_knowledge\_base\_arn) | ARN of the Bedrock Knowledge Base — empty when enable\_knowledge\_base is false |
| <a name="output_knowledge_base_id"></a> [knowledge\_base\_id](#output\_knowledge\_base\_id) | ID of the Bedrock Knowledge Base — empty when enable\_knowledge\_base is false |
| <a name="output_preprocessor_function_arn"></a> [preprocessor\_function\_arn](#output\_preprocessor\_function\_arn) | ARN of the preprocessor Lambda function — empty when enable\_preprocessor is false |
| <a name="output_preprocessor_function_name"></a> [preprocessor\_function\_name](#output\_preprocessor\_function\_name) | Name of the preprocessor Lambda function — empty when enable\_preprocessor is false |
| <a name="output_preprocessor_role_arn"></a> [preprocessor\_role\_arn](#output\_preprocessor\_role\_arn) | ARN of the preprocessor Lambda IAM role — empty when enable\_preprocessor is false |
| <a name="output_vector_bucket_name"></a> [vector\_bucket\_name](#output\_vector\_bucket\_name) | Name of the S3 Vectors bucket — empty when enable\_knowledge\_base is false |
| <a name="output_vector_index_arn"></a> [vector\_index\_arn](#output\_vector\_index\_arn) | ARN of the S3 Vectors index — empty when enable\_knowledge\_base is false |
<!-- END_TF_DOCS -->
