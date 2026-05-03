# Layer: vpc

Deploys the VPC and all networking primitives for the LinkMe AI AgentCore POC.

## Resources created

| Category | Resources |
|---|---|
| Network | VPC, Internet Gateway |
| Subnets | 2 public (ALB), 2 private-app (ECS + AgentCore), 2 private-db (reserved) |
| Routing | Public route table (IGW), private route table (NAT), 6 associations |
| NAT | Elastic IP, NAT Gateway (public subnet AZ1) |
| Observability | CloudWatch log group, IAM role + policy, VPC flow log (ALL traffic) |

## Dependencies

None — this is the root layer.

## Consumed by

- `app` — `vpc_id`, `private_app_subnet_1_id`, `private_app_subnet_2_id`
- `ai` — `vpc_id`, `private_app_subnet_ids`
- `messaging` — `vpc_id`, `private_db_subnet_ids`
- `cicd` — `private_app_subnet_1_id`, `private_app_subnet_2_id`

## Subnet layout

| Name tag | CIDR | Type |
|---|---|---|
| `net-<project>-<env>-public-az1` | `10.143.32.0/24` | Public (AZ1) |
| `net-<project>-<env>-public-az2` | `10.143.33.0/24` | Public (AZ2) |
| `net-<project>-<env>-private-app-az1` | `10.143.34.0/24` | Private — app (AZ1) |
| `net-<project>-<env>-private-app-az2` | `10.143.35.0/24` | Private — app (AZ2) |
| `net-<project>-<env>-data-az1` | `10.143.36.0/24` | Private — DB (AZ1) |
| `net-<project>-<env>-data-az2` | `10.143.37.0/24` | Private — DB (AZ2) |

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
| [aws_cloudwatch_log_group.flow_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_default_security_group.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/default_security_group) | resource |
| [aws_eip.nat](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eip) | resource |
| [aws_flow_log.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/flow_log) | resource |
| [aws_iam_role.flow_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.flow_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_internet_gateway.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/internet_gateway) | resource |
| [aws_nat_gateway.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/nat_gateway) | resource |
| [aws_route.private_default](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route) | resource |
| [aws_route.public_default](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route) | resource |
| [aws_route_table.private](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table) | resource |
| [aws_route_table.public](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table) | resource |
| [aws_route_table_association.private_app_1](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table_association) | resource |
| [aws_route_table_association.private_app_2](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table_association) | resource |
| [aws_route_table_association.private_db_1](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table_association) | resource |
| [aws_route_table_association.private_db_2](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table_association) | resource |
| [aws_route_table_association.public_1](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table_association) | resource |
| [aws_route_table_association.public_2](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table_association) | resource |
| [aws_security_group.vpc_endpoints](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_subnet.private_app_1](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/subnet) | resource |
| [aws_subnet.private_app_2](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/subnet) | resource |
| [aws_subnet.private_db_1](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/subnet) | resource |
| [aws_subnet.private_db_2](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/subnet) | resource |
| [aws_subnet.public_1](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/subnet) | resource |
| [aws_subnet.public_2](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/subnet) | resource |
| [aws_vpc.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc) | resource |
| [aws_vpc_endpoint.interface](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_endpoint) | resource |
| [aws_vpc_endpoint.s3](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_endpoint) | resource |
| [aws_vpc_security_group_ingress_rule.vpc_endpoints_https](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_ingress_rule) | resource |
| [aws_availability_zones.available](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/availability_zones) | data source |
| [aws_iam_policy_document.flow_logs_assume](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.flow_logs_policy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_account_id"></a> [account\_id](#input\_account\_id) | AWS account ID — used in allowed\_account\_ids provider constraint | `string` | n/a | yes |
| <a name="input_az_count"></a> [az\_count](#input\_az\_count) | Number of Availability Zones to use — AZs are auto-discovered from the region | `number` | `2` | no |
| <a name="input_cloudwatch_kms_key_arn"></a> [cloudwatch\_kms\_key\_arn](#input\_cloudwatch\_kms\_key\_arn) | KMS key ARN for CloudWatch log group encryption — leave null to use AWS-managed encryption | `string` | `null` | no |
| <a name="input_env"></a> [env](#input\_env) | Environment short name (e.g. poc, dev, prod) | `string` | n/a | yes |
| <a name="input_env_type"></a> [env\_type](#input\_env\_type) | Environment type for behavior toggles | `string` | n/a | yes |
| <a name="input_log_retention_days"></a> [log\_retention\_days](#input\_log\_retention\_days) | CloudWatch log retention in days — 7 for POC, 90 for nonprod, 365 for prod | `number` | `7` | no |
| <a name="input_project_name"></a> [project\_name](#input\_project\_name) | Project name used in resource naming and log group paths | `string` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | AWS region — used in VPC endpoint service names | `string` | n/a | yes |
| <a name="input_subnet_cidr_private_app_1"></a> [subnet\_cidr\_private\_app\_1](#input\_subnet\_cidr\_private\_app\_1) | CIDR block for private application subnet in AZ1 | `string` | n/a | yes |
| <a name="input_subnet_cidr_private_app_2"></a> [subnet\_cidr\_private\_app\_2](#input\_subnet\_cidr\_private\_app\_2) | CIDR block for private application subnet in AZ2 | `string` | n/a | yes |
| <a name="input_subnet_cidr_private_db_1"></a> [subnet\_cidr\_private\_db\_1](#input\_subnet\_cidr\_private\_db\_1) | CIDR block for private database subnet in AZ1 | `string` | n/a | yes |
| <a name="input_subnet_cidr_private_db_2"></a> [subnet\_cidr\_private\_db\_2](#input\_subnet\_cidr\_private\_db\_2) | CIDR block for private database subnet in AZ2 | `string` | n/a | yes |
| <a name="input_subnet_cidr_public_1"></a> [subnet\_cidr\_public\_1](#input\_subnet\_cidr\_public\_1) | CIDR block for public subnet in AZ1 | `string` | n/a | yes |
| <a name="input_subnet_cidr_public_2"></a> [subnet\_cidr\_public\_2](#input\_subnet\_cidr\_public\_2) | CIDR block for public subnet in AZ2 | `string` | n/a | yes |
| <a name="input_vpc_cidr"></a> [vpc\_cidr](#input\_vpc\_cidr) | CIDR block for the VPC | `string` | n/a | yes |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_nat_gateway_id"></a> [nat\_gateway\_id](#output\_nat\_gateway\_id) | ID of the NAT gateway |
| <a name="output_private_app_subnet_1_id"></a> [private\_app\_subnet\_1\_id](#output\_private\_app\_subnet\_1\_id) | ID of private application subnet in AZ1 |
| <a name="output_private_app_subnet_2_id"></a> [private\_app\_subnet\_2\_id](#output\_private\_app\_subnet\_2\_id) | ID of private application subnet in AZ2 |
| <a name="output_private_app_subnet_ids"></a> [private\_app\_subnet\_ids](#output\_private\_app\_subnet\_ids) | List of private application subnet IDs |
| <a name="output_private_db_subnet_1_id"></a> [private\_db\_subnet\_1\_id](#output\_private\_db\_subnet\_1\_id) | ID of private database subnet in AZ1 |
| <a name="output_private_db_subnet_2_id"></a> [private\_db\_subnet\_2\_id](#output\_private\_db\_subnet\_2\_id) | ID of private database subnet in AZ2 |
| <a name="output_private_db_subnet_ids"></a> [private\_db\_subnet\_ids](#output\_private\_db\_subnet\_ids) | List of private database subnet IDs |
| <a name="output_public_subnet_1_id"></a> [public\_subnet\_1\_id](#output\_public\_subnet\_1\_id) | ID of public subnet in AZ1 |
| <a name="output_public_subnet_2_id"></a> [public\_subnet\_2\_id](#output\_public\_subnet\_2\_id) | ID of public subnet in AZ2 |
| <a name="output_public_subnet_ids"></a> [public\_subnet\_ids](#output\_public\_subnet\_ids) | List of public subnet IDs |
| <a name="output_vpc_cidr"></a> [vpc\_cidr](#output\_vpc\_cidr) | CIDR block of the VPC |
| <a name="output_vpc_id"></a> [vpc\_id](#output\_vpc\_id) | ID of the VPC |
<!-- END_TF_DOCS -->
