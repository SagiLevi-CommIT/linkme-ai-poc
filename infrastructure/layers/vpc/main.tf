data "aws_availability_zones" "available" {
  state = "available"
}

# ============================================================
# VPC
# ============================================================

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = format(local.name_short, "vpc")
    Description = "Main VPC for ${var.project_name} ${var.env} environment"
  }
}

# ============================================================
# Default Security Group - deny all (never attach to resources)
# ============================================================

resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id

  # Intentionally empty - no ingress or egress rules.
  # Overrides the AWS default that allows all inbound from self.

  tags = {
    Name        = format(local.name_fmt, "sgr", "default-deny")
    Description = "Default VPC security group - deny all never attach to resources"
  }
}

# ============================================================
# Internet Gateway
# ============================================================

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name        = format(local.name_short, "igw")
    Description = "Internet gateway for ${var.project_name} ${var.env} VPC"
  }
}

# ============================================================
# Subnets
# ============================================================

# trivy:ignore:AVD-AWS-0164 # Public subnets require map_public_ip_on_launch - ALB requires public subnets
resource "aws_subnet" "public_1" {
  vpc_id                  = aws_vpc.this.id
  availability_zone       = local.azs[0]
  cidr_block              = var.subnet_cidr_public_1
  map_public_ip_on_launch = true

  tags = {
    Name        = format(local.name_fmt, "net", "public-az1")
    Description = "Public subnet in ${local.azs[0]}"
  }
}

# trivy:ignore:AVD-AWS-0164 # Public subnets require map_public_ip_on_launch - ALB requires public subnets
resource "aws_subnet" "public_2" {
  vpc_id                  = aws_vpc.this.id
  availability_zone       = local.azs[1]
  cidr_block              = var.subnet_cidr_public_2
  map_public_ip_on_launch = true

  tags = {
    Name        = format(local.name_fmt, "net", "public-az2")
    Description = "Public subnet in ${local.azs[1]}"
  }
}

resource "aws_subnet" "private_app_1" {
  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[0]
  cidr_block        = var.subnet_cidr_private_app_1

  tags = {
    Name        = format(local.name_fmt, "net", "private-app-az1")
    Description = "Private application subnet in ${local.azs[0]}"
  }
}

resource "aws_subnet" "private_app_2" {
  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[1]
  cidr_block        = var.subnet_cidr_private_app_2

  tags = {
    Name        = format(local.name_fmt, "net", "private-app-az2")
    Description = "Private application subnet in ${local.azs[1]}"
  }
}

resource "aws_subnet" "private_db_1" {
  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[0]
  cidr_block        = var.subnet_cidr_private_db_1

  tags = {
    Name        = format(local.name_fmt, "net", "data-az1")
    Description = "Private database subnet in ${local.azs[0]}"
  }
}

resource "aws_subnet" "private_db_2" {
  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[1]
  cidr_block        = var.subnet_cidr_private_db_2

  tags = {
    Name        = format(local.name_fmt, "net", "data-az2")
    Description = "Private database subnet in ${local.azs[1]}"
  }
}

# ============================================================
# NAT Gateway
# ============================================================

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name        = format(local.name_fmt, "eip", "nat-1")
    Description = "Elastic IP for NAT gateway 1"
  }
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public_1.id

  tags = {
    Name        = format(local.name_fmt, "nat", "gateway-1")
    Description = "NAT gateway for private subnets in ${local.azs[0]}"
  }
}

# ============================================================
# Route Tables
# ============================================================

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name        = format(local.name_fmt, "rt", "public")
    Description = "Route table for public subnets - default route via IGW"
  }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name        = format(local.name_fmt, "rt", "private")
    Description = "Route table for private subnets - default route via NAT"
  }
}

# ============================================================
# Routes
# ============================================================

resource "aws_route" "public_default" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route" "private_default" {
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this.id
}

# ============================================================
# Route Table Associations
# ============================================================

resource "aws_route_table_association" "public_1" {
  route_table_id = aws_route_table.public.id
  subnet_id      = aws_subnet.public_1.id
}

resource "aws_route_table_association" "public_2" {
  route_table_id = aws_route_table.public.id
  subnet_id      = aws_subnet.public_2.id
}

resource "aws_route_table_association" "private_app_1" {
  route_table_id = aws_route_table.private.id
  subnet_id      = aws_subnet.private_app_1.id
}

resource "aws_route_table_association" "private_app_2" {
  route_table_id = aws_route_table.private.id
  subnet_id      = aws_subnet.private_app_2.id
}

resource "aws_route_table_association" "private_db_1" {
  route_table_id = aws_route_table.private.id
  subnet_id      = aws_subnet.private_db_1.id
}

resource "aws_route_table_association" "private_db_2" {
  route_table_id = aws_route_table.private.id
  subnet_id      = aws_subnet.private_db_2.id
}

# ============================================================
# VPC Flow Logs
# ============================================================

resource "aws_cloudwatch_log_group" "flow_logs" {
  name              = "/aws/vpc/flowlogs/${var.project_name}-${var.env}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.cloudwatch_kms_key_arn

  tags = {
    Name        = format(local.name_fmt, "log", "vpc-flowlogs")
    Description = "CloudWatch log group for VPC flow logs"
  }
}

data "aws_iam_policy_document" "flow_logs_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "flow_logs" {
  name = format(local.name_fmt, "role", "vpc-flow-logs")

  assume_role_policy = data.aws_iam_policy_document.flow_logs_assume.json

  tags = {
    Name        = format(local.name_fmt, "role", "vpc-flow-logs")
    Description = "IAM role allowing VPC flow logs to deliver to CloudWatch"
  }
}

data "aws_iam_policy_document" "flow_logs_policy" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
    ]
    resources = [
      aws_cloudwatch_log_group.flow_logs.arn,
      "${aws_cloudwatch_log_group.flow_logs.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "flow_logs" {
  name   = "flowlogsDeliveryRolePolicy"
  role   = aws_iam_role.flow_logs.id
  policy = data.aws_iam_policy_document.flow_logs_policy.json
}

resource "aws_flow_log" "this" {
  vpc_id          = aws_vpc.this.id
  traffic_type    = "ALL"
  iam_role_arn    = aws_iam_role.flow_logs.arn
  log_destination = aws_cloudwatch_log_group.flow_logs.arn

  tags = {
    Name        = format(local.name_fmt, "flowlog", "vpc")
    Description = "VPC flow log delivering all traffic to CloudWatch"
  }
}
