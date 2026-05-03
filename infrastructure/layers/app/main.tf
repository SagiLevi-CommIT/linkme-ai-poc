# Resources in this layer are split across purpose-specific files:
#   ecr.tf  - ECR repositories (for_each), KMS key, lifecycle policies, scanning
#   iam.tf  - ECS execution role, ECS task role, backend role (conditional by backend_type)
#   alb.tf  - Security groups, ALB, target group, listeners
#   ecs.tf  - ECS cluster, CloudWatch log groups, ECS backend service, Lambda backend function
#   waf.tf  - WAFv2 WebACL and ALB association (enabled via var.enable_waf)
#
# Backend compute types (var.backend_type):
#   agentcore - Bedrock AgentCore runtime (IAM role, SG, log group; runtime deployed via CI/CD)
#   ecs       - ECS Fargate service (task definition, service, IAM role, SG, log group)
#   lambda    - Lambda function (container image from ECR, IAM role, optional VPC, log group)
#   none      - No backend compute resources
