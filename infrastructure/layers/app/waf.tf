# ============================================================
# WAFv2 WebACL - attached to the public ALB
# Enabled via var.enable_waf (default false for POC, true for production)
# ============================================================

resource "aws_wafv2_web_acl" "this" {
  count = local.enable_frontend && var.enable_waf ? 1 : 0

  name  = format(local.name_fmt, "waf", "alb")
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 1

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-${var.env}-waf-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 2

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-${var.env}-waf-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = format(local.name_fmt, "waf", "alb")
    sampled_requests_enabled   = true
  }

  tags = {
    Name        = format(local.name_fmt, "waf", "alb")
    Description = "WAFv2 WebACL protecting the ${var.project_name} ALB - AWS managed common and bad-inputs rules"
  }
}

resource "aws_wafv2_web_acl_association" "this" {
  count = local.enable_frontend && var.enable_waf ? 1 : 0

  resource_arn = aws_lb.this[0].arn
  web_acl_arn  = aws_wafv2_web_acl.this[0].arn
}
