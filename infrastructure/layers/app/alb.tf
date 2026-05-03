# ============================================================
# Security Groups
# ============================================================

resource "aws_security_group" "alb" {
  count       = local.enable_frontend ? 1 : 0
  name        = format(local.name_fmt, "sgr", "alb")
  description = "Security group for internet-facing Application Load Balancer"
  vpc_id      = var.vpc_id

  tags = {
    Name        = format(local.name_fmt, "sgr", "alb")
    Description = "Security group for internet-facing ALB - HTTP/HTTPS inbound"
  }
}

resource "aws_security_group" "ecs" {
  count       = local.enable_frontend ? 1 : 0
  name        = format(local.name_fmt, "sgr", "ecs")
  description = "Security group for ECS Fargate frontend tasks"
  vpc_id      = var.vpc_id

  tags = {
    Name        = format(local.name_fmt, "sgr", "ecs")
    Description = "Security group for ECS tasks - app port from ALB only"
  }
}

resource "aws_security_group" "backend" {
  count       = local.has_backend ? 1 : 0
  name        = format(local.name_fmt, "sgr", local.backend_role_suffix[var.backend_type])
  description = local.backend_sg_description[var.backend_type]
  vpc_id      = var.vpc_id

  tags = {
    Name        = format(local.name_fmt, "sgr", local.backend_role_suffix[var.backend_type])
    Description = "${local.backend_sg_description[var.backend_type]} - port ${var.backend_container_port} from ECS only"
  }
}

# ============================================================
# Security Group Rules
# ============================================================

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  count             = local.enable_frontend ? 1 : 0
  security_group_id = aws_security_group.alb[0].id
  description       = "HTTP from anywhere"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  count             = local.enable_frontend ? 1 : 0
  security_group_id = aws_security_group.alb[0].id
  description       = "HTTPS from anywhere"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

# trivy:ignore:AVD-AWS-0104 # Unrestricted egress required - ALB must reach ECS on dynamic ports
resource "aws_vpc_security_group_egress_rule" "alb_all" {
  count             = local.enable_frontend ? 1 : 0
  security_group_id = aws_security_group.alb[0].id
  description       = "All outbound traffic"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "ecs_app" {
  count                        = local.enable_frontend ? 1 : 0
  security_group_id            = aws_security_group.ecs[0].id
  description                  = "Application port from ALB"
  from_port                    = var.app_container_port
  to_port                      = var.app_container_port
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.alb[0].id
}

# trivy:ignore:AVD-AWS-0104 # Unrestricted egress required - ECS must reach ECR, backend, and external endpoints
resource "aws_vpc_security_group_egress_rule" "ecs_all" {
  count             = local.enable_frontend ? 1 : 0
  security_group_id = aws_security_group.ecs[0].id
  description       = "All outbound traffic"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# Backend ingress from frontend (agentcore and ecs - Lambda is invoked, not called on a port)
resource "aws_vpc_security_group_ingress_rule" "backend_from_frontend" {
  count                        = local.enable_frontend && (local.is_agentcore || local.is_ecs_backend) ? 1 : 0
  security_group_id            = aws_security_group.backend[0].id
  description                  = "Backend API from frontend ECS tasks"
  from_port                    = var.backend_container_port
  to_port                      = var.backend_container_port
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.ecs[0].id
}

# trivy:ignore:AVD-AWS-0104 # Unrestricted egress required - backend must reach Bedrock, S3, and ECR endpoints
resource "aws_vpc_security_group_egress_rule" "backend_all" {
  count             = local.has_backend ? 1 : 0
  security_group_id = aws_security_group.backend[0].id
  description       = "All outbound traffic (Bedrock, S3, external APIs)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ============================================================
# Application Load Balancer
# ============================================================

# trivy:ignore:AVD-AWS-0053 # Internet-facing ALB is intentional - frontend must be publicly accessible
# trivy:ignore:AVD-AWS-0054 # HTTP-only is intentional for POC - enable HTTPS by setting certificate_arn
resource "aws_lb" "this" {
  count                      = local.enable_frontend ? 1 : 0
  name                       = format(local.name_short, "alb")
  internal                   = false
  load_balancer_type         = "application"
  ip_address_type            = "ipv4"
  security_groups            = [aws_security_group.alb[0].id]
  subnets                    = [var.public_subnet_1_id, var.public_subnet_2_id]
  drop_invalid_header_fields = true
  enable_deletion_protection = var.enable_alb_deletion_protection

  dynamic "access_logs" {
    for_each = var.alb_access_logs_bucket != "" ? [1] : []
    content {
      bucket  = var.alb_access_logs_bucket
      prefix  = "alb/${var.project_name}-${var.env}"
      enabled = true
    }
  }

  tags = {
    Name        = format(local.name_short, "alb")
    Description = "Internet-facing ALB for the ${var.project_name} frontend"
  }
}

resource "aws_lb_target_group" "frontend" {
  count       = local.enable_frontend ? 1 : 0
  name        = format(local.name_fmt, "tg", "frontend")
  port        = var.app_container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name        = format(local.name_fmt, "tg", "frontend")
    Description = "Target group for ECS Fargate frontend tasks on port ${var.app_container_port}"
  }
}

# trivy:ignore:AVD-AWS-0054 # HTTP listener intentional for POC - set certificate_arn to enable HTTPS redirect
resource "aws_lb_listener" "http" {
  count             = local.enable_frontend ? 1 : 0
  load_balancer_arn = aws_lb.this[0].arn
  port              = 80
  protocol          = "HTTP"

  # Redirect to HTTPS when a certificate is provided; forward directly for HTTP-only deployments
  default_action {
    type             = var.certificate_arn != "" ? "redirect" : "forward"
    target_group_arn = var.certificate_arn != "" ? null : aws_lb_target_group.frontend[0].arn

    dynamic "redirect" {
      for_each = var.certificate_arn != "" ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = local.enable_frontend && var.certificate_arn != "" ? 1 : 0
  load_balancer_arn = aws_lb.this[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend[0].arn
  }
}
