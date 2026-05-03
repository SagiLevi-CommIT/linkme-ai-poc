# Layer: messaging

Deploys the Phase 2 messaging and service infrastructure for the LinkMe AI POC: SQS queues, MemoryDB for Redis, Phase 2 ECS services, auto-scaling, and CloudWatch alarms.

## Resources created

| Category | Condition | Resources |
|---|---|---|
| SQS | `enable_messaging` | AI queue + DLQ, Publisher queue + DLQ (SSE-SQS encrypted) |
| MemoryDB | `enable_memorydb` | Redis 7.1 cluster, subnet group, parameter group, ACL (TLS enabled) |
| ECS | `enable_phase2_services` | 4 task definitions + services (AI Message Processor, AI Service, Instagram Mock, Publisher Mock) |
| IAM | per service | Task roles with scoped SQS, MemoryDB, Bedrock, CloudWatch policies |
| Security Groups | per resource | MemoryDB SG (port 6379), 4 ECS service SGs |
| Auto-Scaling | `enable_autoscaling` | 5x scale-out / 1x scale-in per ECS service (CPU target tracking) |
| CloudWatch | per resource | 4 log groups + 4 SQS alarms (queue depth + DLQ non-empty) |

## Feature flags

| Flag | Default | Purpose |
|---|---|---|
| `enable_messaging` | `false` | SQS queues — can be created without app code |
| `enable_memorydb` | `false` | MemoryDB cluster — can be created without app code |
| `enable_phase2_services` | `false` | ECS services — requires app code in ECR |
| `enable_autoscaling` | `false` | Auto-scaling — enable after services are running |

## Dependencies

- `vpc` — `vpc_id`, `private_app_subnet_ids`, `private_db_subnet_ids`
- `app` — `ecs_cluster_arn`, `ecs_task_execution_role_arn`, `ecr_repository_uris`

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
| [aws_appautoscaling_policy.cpu](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/appautoscaling_policy) | resource |
| [aws_appautoscaling_target.services](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/appautoscaling_target) | resource |
| [aws_cloudwatch_log_group.ai_message_processor](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_log_group.ai_service](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_log_group.instagram_mock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_log_group.publisher_mock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_metric_alarm.ai_dlq_messages](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_cloudwatch_metric_alarm.ai_queue_depth](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_cloudwatch_metric_alarm.publisher_dlq_messages](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_cloudwatch_metric_alarm.publisher_queue_depth](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_ecs_service.ai_message_processor](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_service) | resource |
| [aws_ecs_service.ai_service](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_service) | resource |
| [aws_ecs_service.instagram_mock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_service) | resource |
| [aws_ecs_service.publisher_mock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_service) | resource |
| [aws_ecs_task_definition.ai_message_processor](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_task_definition) | resource |
| [aws_ecs_task_definition.ai_service](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_task_definition) | resource |
| [aws_ecs_task_definition.instagram_mock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_task_definition) | resource |
| [aws_ecs_task_definition.publisher_mock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_task_definition) | resource |
| [aws_iam_policy.phase2_cloudwatch](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_policy) | resource |
| [aws_iam_role.ai_message_processor](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.ai_service](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.instagram_mock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.publisher_mock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.ai_message_processor_bedrock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.ai_message_processor_kb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.ai_message_processor_sqs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.ai_service_bedrock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.ai_service_kb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.ai_service_sqs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.instagram_mock_sqs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.publisher_mock_sqs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy_attachment.ai_message_processor_cloudwatch](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_iam_role_policy_attachment.ai_service_cloudwatch](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_iam_role_policy_attachment.instagram_mock_cloudwatch](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_iam_role_policy_attachment.publisher_mock_cloudwatch](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_memorydb_cluster.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/memorydb_cluster) | resource |
| [aws_memorydb_parameter_group.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/memorydb_parameter_group) | resource |
| [aws_memorydb_subnet_group.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/memorydb_subnet_group) | resource |
| [aws_security_group.ai_message_processor](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_security_group.ai_service](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_security_group.instagram_mock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_security_group.memorydb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_security_group.publisher_mock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_sqs_queue.ai](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue) | resource |
| [aws_sqs_queue.ai_dlq](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue) | resource |
| [aws_sqs_queue.publisher](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue) | resource |
| [aws_sqs_queue.publisher_dlq](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue) | resource |
| [aws_sqs_queue_redrive_allow_policy.ai_dlq](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue_redrive_allow_policy) | resource |
| [aws_sqs_queue_redrive_allow_policy.publisher_dlq](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue_redrive_allow_policy) | resource |
| [aws_vpc_security_group_egress_rule.ai_message_processor_all](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_egress_rule) | resource |
| [aws_vpc_security_group_egress_rule.ai_service_all](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_egress_rule) | resource |
| [aws_vpc_security_group_egress_rule.instagram_mock_all](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_egress_rule) | resource |
| [aws_vpc_security_group_egress_rule.publisher_mock_all](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_egress_rule) | resource |
| [aws_vpc_security_group_ingress_rule.memorydb_from_ai_processor](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_ingress_rule) | resource |
| [aws_vpc_security_group_ingress_rule.memorydb_from_ai_service](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_ingress_rule) | resource |
| [aws_iam_policy_document.ai_message_processor_bedrock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.ai_message_processor_kb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.ai_message_processor_sqs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.ai_service_bedrock](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.ai_service_kb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.ai_service_sqs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.ecs_assume](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.instagram_mock_sqs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.phase2_cloudwatch](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.publisher_mock_sqs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_account_id"></a> [account\_id](#input\_account\_id) | AWS account ID — used in allowed\_account\_ids provider constraint and IAM policy ARNs | `string` | n/a | yes |
| <a name="input_autoscaling_config"></a> [autoscaling\_config](#input\_autoscaling\_config) | ECS auto-scaling configuration for Phase 2 services | <pre>object({<br>    min_capacity       = optional(number, 1)<br>    max_capacity       = optional(number, 5)<br>    scale_out_cooldown = optional(number, 60)<br>    scale_in_cooldown  = optional(number, 300)<br>  })</pre> | `{}` | no |
| <a name="input_bedrock_model_arns"></a> [bedrock\_model\_arns](#input\_bedrock\_model\_arns) | Bedrock foundation model ARNs the AI services may invoke — leave empty to skip policy | `list(string)` | `[]` | no |
| <a name="input_cloudwatch_kms_key_arn"></a> [cloudwatch\_kms\_key\_arn](#input\_cloudwatch\_kms\_key\_arn) | KMS key ARN for CloudWatch log group encryption — leave null to use AWS-managed encryption | `string` | `null` | no |
| <a name="input_ecr_repository_uris"></a> [ecr\_repository\_uris](#input\_ecr\_repository\_uris) | Map of ECR repo key to URI — from app layer | `map(string)` | `{}` | no |
| <a name="input_ecs_cluster_arn"></a> [ecs\_cluster\_arn](#input\_ecs\_cluster\_arn) | ARN of the ECS cluster — from app layer | `string` | n/a | yes |
| <a name="input_ecs_task_execution_role_arn"></a> [ecs\_task\_execution\_role\_arn](#input\_ecs\_task\_execution\_role\_arn) | ARN of the ECS task execution role — from app layer | `string` | n/a | yes |
| <a name="input_enable_autoscaling"></a> [enable\_autoscaling](#input\_enable\_autoscaling) | Create ECS auto-scaling for Phase 2 services — enable after services are running | `bool` | `false` | no |
| <a name="input_enable_bedrock_knowledge_base"></a> [enable\_bedrock\_knowledge\_base](#input\_enable\_bedrock\_knowledge\_base) | Grant AI service roles access to Bedrock Knowledge Bases | `bool` | `false` | no |
| <a name="input_enable_memorydb"></a> [enable\_memorydb](#input\_enable\_memorydb) | Create MemoryDB for Redis cluster | `bool` | `false` | no |
| <a name="input_enable_messaging"></a> [enable\_messaging](#input\_enable\_messaging) | Create SQS queues (ai + publisher) with DLQs | `bool` | `false` | no |
| <a name="input_enable_phase2_services"></a> [enable\_phase2\_services](#input\_enable\_phase2\_services) | Create Phase 2 ECS services — requires application code in ECR | `bool` | `false` | no |
| <a name="input_env"></a> [env](#input\_env) | Environment short name (e.g. poc, dev, prod) | `string` | n/a | yes |
| <a name="input_env_type"></a> [env\_type](#input\_env\_type) | Environment type for behavior toggles | `string` | n/a | yes |
| <a name="input_log_retention_days"></a> [log\_retention\_days](#input\_log\_retention\_days) | CloudWatch log retention in days — 7 for POC, 90 for nonprod, 365 for prod | `number` | `7` | no |
| <a name="input_memorydb_config"></a> [memorydb\_config](#input\_memorydb\_config) | MemoryDB cluster configuration | <pre>object({<br>    node_type                = optional(string, "db.t4g.small")<br>    num_shards               = optional(number, 1)<br>    num_replicas_per_shard   = optional(number, 1)<br>    engine_version           = optional(string, "7.1")<br>    snapshot_retention_limit = optional(number, 1)<br>    maintenance_window       = optional(string, "sun:05:00-sun:06:00")<br>    port                     = optional(number, 6379)<br>  })</pre> | `{}` | no |
| <a name="input_phase2_ecs_config"></a> [phase2\_ecs\_config](#input\_phase2\_ecs\_config) | ECS configuration shared by all Phase 2 services | <pre>object({<br>    cpu           = optional(number, 512)<br>    memory        = optional(number, 1024)<br>    desired_count = optional(number, 0)<br>    image_tag     = optional(string, "latest")<br>  })</pre> | `{}` | no |
| <a name="input_private_app_subnet_ids"></a> [private\_app\_subnet\_ids](#input\_private\_app\_subnet\_ids) | List of private application subnet IDs — from vpc layer, used for ECS services | `list(string)` | `[]` | no |
| <a name="input_private_db_subnet_ids"></a> [private\_db\_subnet\_ids](#input\_private\_db\_subnet\_ids) | List of private database subnet IDs — from vpc layer, used for MemoryDB subnet group | `list(string)` | `[]` | no |
| <a name="input_project_name"></a> [project\_name](#input\_project\_name) | Project name used in resource naming | `string` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | AWS region — used in IAM policy ARNs | `string` | n/a | yes |
| <a name="input_sqs_config"></a> [sqs\_config](#input\_sqs\_config) | SQS queue configuration | <pre>object({<br>    ai_visibility_timeout        = optional(number, 300)<br>    publisher_visibility_timeout = optional(number, 60)<br>    message_retention_seconds    = optional(number, 345600)<br>    dlq_max_receive_count        = optional(number, 3)<br>  })</pre> | `{}` | no |
| <a name="input_vpc_id"></a> [vpc\_id](#input\_vpc\_id) | ID of the VPC — from vpc layer | `string` | n/a | yes |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_ai_message_processor_role_arn"></a> [ai\_message\_processor\_role\_arn](#output\_ai\_message\_processor\_role\_arn) | ARN of the AI Message Processor IAM role — empty when enable\_phase2\_services is false |
| <a name="output_ai_message_processor_service_name"></a> [ai\_message\_processor\_service\_name](#output\_ai\_message\_processor\_service\_name) | Name of the AI Message Processor ECS service — empty when enable\_phase2\_services is false |
| <a name="output_ai_service_role_arn"></a> [ai\_service\_role\_arn](#output\_ai\_service\_role\_arn) | ARN of the AI Service IAM role — empty when enable\_phase2\_services is false |
| <a name="output_ai_service_service_name"></a> [ai\_service\_service\_name](#output\_ai\_service\_service\_name) | Name of the AI Service ECS service — empty when enable\_phase2\_services is false |
| <a name="output_instagram_mock_role_arn"></a> [instagram\_mock\_role\_arn](#output\_instagram\_mock\_role\_arn) | ARN of the Instagram MockService IAM role — empty when enable\_phase2\_services is false |
| <a name="output_instagram_mock_service_name"></a> [instagram\_mock\_service\_name](#output\_instagram\_mock\_service\_name) | Name of the Instagram MockService ECS service — empty when enable\_phase2\_services is false |
| <a name="output_memorydb_cluster_arn"></a> [memorydb\_cluster\_arn](#output\_memorydb\_cluster\_arn) | ARN of the MemoryDB cluster — empty when enable\_memorydb is false |
| <a name="output_memorydb_cluster_endpoint"></a> [memorydb\_cluster\_endpoint](#output\_memorydb\_cluster\_endpoint) | Endpoint of the MemoryDB cluster — null when enable\_memorydb is false |
| <a name="output_memorydb_security_group_id"></a> [memorydb\_security\_group\_id](#output\_memorydb\_security\_group\_id) | ID of the MemoryDB security group — empty when enable\_memorydb is false |
| <a name="output_publisher_mock_role_arn"></a> [publisher\_mock\_role\_arn](#output\_publisher\_mock\_role\_arn) | ARN of the Publisher MockService IAM role — empty when enable\_phase2\_services is false |
| <a name="output_publisher_mock_service_name"></a> [publisher\_mock\_service\_name](#output\_publisher\_mock\_service\_name) | Name of the Publisher MockService ECS service — empty when enable\_phase2\_services is false |
| <a name="output_sqs_ai_dlq_arn"></a> [sqs\_ai\_dlq\_arn](#output\_sqs\_ai\_dlq\_arn) | ARN of the AI dead-letter queue — empty when enable\_messaging is false |
| <a name="output_sqs_ai_queue_arn"></a> [sqs\_ai\_queue\_arn](#output\_sqs\_ai\_queue\_arn) | ARN of the AI SQS queue — empty when enable\_messaging is false |
| <a name="output_sqs_ai_queue_url"></a> [sqs\_ai\_queue\_url](#output\_sqs\_ai\_queue\_url) | URL of the AI SQS queue — empty when enable\_messaging is false |
| <a name="output_sqs_publisher_dlq_arn"></a> [sqs\_publisher\_dlq\_arn](#output\_sqs\_publisher\_dlq\_arn) | ARN of the Publisher dead-letter queue — empty when enable\_messaging is false |
| <a name="output_sqs_publisher_queue_arn"></a> [sqs\_publisher\_queue\_arn](#output\_sqs\_publisher\_queue\_arn) | ARN of the Publisher SQS queue — empty when enable\_messaging is false |
| <a name="output_sqs_publisher_queue_url"></a> [sqs\_publisher\_queue\_url](#output\_sqs\_publisher\_queue\_url) | URL of the Publisher SQS queue — empty when enable\_messaging is false |
<!-- END_TF_DOCS -->
