# ============================================================
# VPC Endpoints - keep AWS traffic off the public internet
# ============================================================

# S3 Gateway endpoint (free - no hourly charge)
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name        = format(local.name_fmt, "vpce", "s3")
    Description = "S3 gateway endpoint avoids NAT for S3 traffic"
  }
}

# DynamoDB Gateway endpoint (free - no hourly charge)
resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name        = format(local.name_fmt, "vpce", "dynamodb")
    Description = "DynamoDB gateway endpoint avoids NAT for DDB traffic"
  }
}

# ============================================================
# Interface Endpoints - SG + private subnets
# ============================================================

resource "aws_security_group" "vpc_endpoints" {
  name        = format(local.name_fmt, "sgr", "vpc-endpoints")
  description = "HTTPS from VPC CIDR to VPC interface endpoints"
  vpc_id      = aws_vpc.this.id

  tags = {
    Name        = format(local.name_fmt, "sgr", "vpc-endpoints")
    Description = "Security group for VPC interface endpoints - HTTPS from VPC only"
  }
}

resource "aws_vpc_security_group_ingress_rule" "vpc_endpoints_https" {
  security_group_id = aws_security_group.vpc_endpoints.id
  description       = "HTTPS from VPC CIDR"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = var.vpc_cidr
}

locals {
  # Interface endpoints to create - each costs ~$0.01/hr per AZ
  interface_endpoints = {
    bedrock-runtime       = "com.amazonaws.${var.region}.bedrock-runtime"
    bedrock-agent-runtime = "com.amazonaws.${var.region}.bedrock-agent-runtime"
    ecr-dkr               = "com.amazonaws.${var.region}.ecr.dkr"
    ecr-api               = "com.amazonaws.${var.region}.ecr.api"
    logs                  = "com.amazonaws.${var.region}.logs"
    sqs                   = "com.amazonaws.${var.region}.sqs"
    sagemaker-runtime     = "com.amazonaws.${var.region}.sagemaker.runtime"
    sts                   = "com.amazonaws.${var.region}.sts"
    secretsmanager        = "com.amazonaws.${var.region}.secretsmanager"
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each = local.interface_endpoints

  vpc_id              = aws_vpc.this.id
  service_name        = each.value
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_app_1.id, aws_subnet.private_app_2.id]
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name        = format(local.name_fmt, "vpce", each.key)
    Description = "Interface endpoint for ${each.key}"
  }
}
