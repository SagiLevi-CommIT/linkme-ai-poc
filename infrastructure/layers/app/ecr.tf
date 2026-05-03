# ============================================================
# KMS Key for ECR Encryption
# ============================================================

data "aws_iam_policy_document" "ecr_kms" {
  # Named admins: explicit key administration (create, rotate, disable, delete)
  # Root is retained below as emergency break-glass only - do not remove or the
  # key becomes unrecoverable if all admin roles are deleted.
  dynamic "statement" {
    for_each = length(var.kms_admin_role_arns) > 0 ? [1] : []
    content {
      sid    = "KeyAdministration"
      effect = "Allow"
      principals {
        type        = "AWS"
        identifiers = var.kms_admin_role_arns
      }
      # Management-only actions - explicitly enumerated, no wildcards.
      # Does not include data-plane kms:Decrypt / kms:GenerateDataKey.
      # kms:ScheduleKeyDeletion is intentionally on root break-glass only.
      actions = [
        "kms:CancelKeyDeletion",
        "kms:CreateAlias",
        "kms:CreateGrant",
        "kms:DeleteAlias",
        "kms:DescribeKey",
        "kms:DisableKey",
        "kms:DisableKeyRotation",
        "kms:EnableKey",
        "kms:EnableKeyRotation",
        "kms:GetKeyPolicy",
        "kms:GetKeyRotationStatus",
        "kms:ListGrants",
        "kms:ListKeyPolicies",
        "kms:ListResourceTags",
        "kms:PutKeyPolicy",
        "kms:RevokeGrant",
        "kms:TagResource",
        "kms:UntagResource",
        "kms:UpdateAlias",
        "kms:UpdateKeyDescription",
      ]
      resources = ["*"]
    }
  }

  # Emergency break-glass: account root can recover the key if all admin roles are deleted.
  # Root cannot use this grant directly - it requires an explicit Allow in the caller's
  # own IAM policy, which should be restricted to a dedicated break-glass process.
  statement {
    sid    = "RootBreakGlass"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${var.account_id}:root"]
    }
    actions   = ["kms:*"]
    resources = ["*"]
  }

  # ECR service: encrypt/decrypt repository contents - scoped to this account and region
  statement {
    sid    = "ECRServiceAccess"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["ecr.amazonaws.com"]
    }
    actions = [
      "kms:GenerateDataKey",
      "kms:Decrypt",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:CallerAccount"
      values   = [var.account_id]
    }
    condition {
      test     = "StringLike"
      variable = "kms:ViaService"
      values   = ["ecr.${var.region}.amazonaws.com"]
    }
  }

  # Roles that pull images: ECS task execution and backend (when present)
  statement {
    sid    = "ImagePullAccess"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = local.ecr_kms_pull_role_arns
    }
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
    ]
    resources = ["*"]
  }
}

resource "aws_kms_key" "ecr" {
  description             = "KMS key for ECR repository encryption - ${var.project_name} ${var.env}"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.ecr_kms.json

  tags = {
    Name        = format(local.name_fmt, "kms", "ecr")
    Description = "KMS key used to encrypt ECR images for ${var.project_name}"
  }
}

resource "aws_kms_alias" "ecr" {
  name          = "alias/${var.project_name}-${var.env}-ecr"
  target_key_id = aws_kms_key.ecr.key_id
}

# ============================================================
# ECR Repositories
# ============================================================

resource "aws_ecr_repository" "this" {
  for_each = var.ecr_repositories

  name                 = "${var.project_name}-${var.env}-${each.key}"
  image_tag_mutability = "IMMUTABLE"

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.ecr.arn
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = format(local.name_fmt, "ecr", each.key)
    Description = "ECR repository for ${var.project_name} - ${each.value}"
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = var.ecr_repositories
  repository = aws_ecr_repository.this[each.key].name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# ============================================================
# Registry Enhanced Scanning
# ============================================================

resource "aws_ecr_registry_scanning_configuration" "this" {
  scan_type = "ENHANCED"

  rule {
    scan_frequency = "CONTINUOUS_SCAN"

    repository_filter {
      filter      = "${var.project_name}-*"
      filter_type = "WILDCARD"
    }
  }
}

# ============================================================
# Repository Policies (restrict push to known CI/CD roles)
# Set ecr_push_role_arns after cicd layer deploy, then re-apply.
# ============================================================

data "aws_iam_policy_document" "ecr_push" {
  for_each = local.ecr_push_repos

  statement {
    sid    = "AllowPushFromCICD"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = [each.value]
    }
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
    ]
  }
}

resource "aws_ecr_repository_policy" "this" {
  for_each   = local.ecr_push_repos
  repository = aws_ecr_repository.this[each.key].name
  policy     = data.aws_iam_policy_document.ecr_push[each.key].json
}
