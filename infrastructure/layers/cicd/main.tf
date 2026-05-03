# ============================================================
# S3 Artifacts Bucket
# ============================================================

# trivy:ignore:AVD-AWS-0132 # AES256 (AWS-managed) encryption is sufficient for ephemeral build artifacts
resource "aws_s3_bucket" "artifacts" {
  bucket = "${var.project_name}-${var.env}-codebuild-artifacts-${var.account_id}"

  tags = {
    Name        = format(local.name_fmt, "bkt", "codebuild-artifacts")
    Description = "S3 bucket storing CodeBuild build artifacts for ${var.project_name}"
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "DeleteOldArtifacts"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# trivy:ignore:AVD-AWS-0132 # AES256 (AWS-managed) encryption is sufficient for ephemeral build artifacts
resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket" "access_logs" {
  bucket = "${var.project_name}-${var.env}-s3-access-logs-${var.account_id}"

  tags = {
    Name        = format(local.name_fmt, "bkt", "s3-access-logs")
    Description = "S3 server access logs for ${var.project_name} ${var.env} buckets"
  }
}

resource "aws_s3_bucket_public_access_block" "access_logs" {
  bucket                  = aws_s3_bucket.access_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_ownership_controls" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    # BucketOwnerPreferred required for S3 server access log delivery
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    id     = "ExpireOldLogs"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "access_logs_bucket_policy" {
  statement {
    sid    = "S3ServerAccessLogsPolicy"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.access_logs.arn}/*"]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.artifacts.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  policy = data.aws_iam_policy_document.access_logs_bucket_policy.json

  # Public access block must be applied before the bucket policy or AWS rejects
  # the policy with "conflicting conditional operations" on the same bucket.
  depends_on = [aws_s3_bucket_public_access_block.access_logs]
}

resource "aws_s3_bucket_logging" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "s3-access-logs/${var.project_name}-${var.env}-codebuild-artifacts/"

  # Logging config requires the target bucket policy (granting logging.s3.amazonaws.com
  # s3:PutObject) to exist first, otherwise the first log delivery attempt fails.
  depends_on = [aws_s3_bucket_policy.access_logs]
}

data "aws_iam_policy_document" "artifacts_ssl_only" {
  statement {
    sid    = "DenyNonSSL"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*",
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  policy = data.aws_iam_policy_document.artifacts_ssl_only.json

  # Public access block must be applied before the bucket policy - same ordering
  # constraint as the access_logs bucket above.
  depends_on = [aws_s3_bucket_public_access_block.artifacts]
}

# ============================================================
# IAM Roles (one per CodeBuild project)
# ============================================================

data "aws_iam_policy_document" "codebuild_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codebuild" {
  for_each = var.codebuild_projects

  name               = format(local.name_fmt, "role", "codebuild-${each.key}")
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json

  tags = {
    Name        = format(local.name_fmt, "role", "codebuild-${each.key}")
    Description = "IAM role for CodeBuild ${each.key} build project"
  }
}

# ECR push policy (only for projects with an ecr_repo_key)
resource "aws_iam_role_policy" "codebuild_ecr" {
  for_each = local.codebuild_ecr_projects

  name = "ECRPush"
  role = aws_iam_role.codebuild[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
        ]
        Resource = var.ecr_repository_arns[each.value.ecr_repo_key]
      }
    ]
  })
}

# Base policy (logs, codecommit, s3 artifacts, iam:PassRole)
resource "aws_iam_role_policy" "codebuild_base" {
  for_each = var.codebuild_projects

  name = "CodeBuildBase"
  role = aws_iam_role.codebuild[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          aws_cloudwatch_log_group.codebuild[each.key].arn,
          "${aws_cloudwatch_log_group.codebuild[each.key].arn}:*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["codecommit:GitPull"]
        Resource = "arn:aws:codecommit:${var.region}:${var.account_id}:${var.codecommit_repo_name}"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:GetBucketAcl",
          "s3:GetBucketLocation",
        ]
        Resource = [
          aws_s3_bucket.artifacts.arn,
          "${aws_s3_bucket.artifacts.arn}/*",
        ]
      },
      {
        # Scoped to specific role ARNs from app layer outputs (passed via codebuild_pass_role_arns).
        # Falls back to project+env wildcard if the variable is empty (first-deploy bootstrap).
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = length(var.codebuild_pass_role_arns) > 0 ? var.codebuild_pass_role_arns : [
          "arn:aws:iam::${var.account_id}:role/${var.project_name}-${var.env}-*"
        ]
        Condition = {
          StringEquals = {
            "iam:PassedToService" = [
              "ecs-tasks.amazonaws.com",
              "bedrock-agentcore.amazonaws.com",
            ]
          }
        }
      }
    ]
  })
}

# Extra IAM policies (project-specific permissions passed from Terragrunt)
resource "aws_iam_role_policy" "codebuild_extra" {
  for_each = var.codebuild_extra_iam_policies

  name   = "ExtraPermissions"
  role   = aws_iam_role.codebuild[each.key].id
  policy = each.value
}

# ============================================================
# CloudWatch Log Groups (one per CodeBuild project)
# ============================================================

resource "aws_cloudwatch_log_group" "codebuild" {
  for_each = var.codebuild_projects

  name              = "/aws/codebuild/${var.project_name}-${var.env}-${each.key}-build"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.cloudwatch_kms_key_arn

  tags = {
    Name        = format(local.name_fmt, "log", "codebuild-${each.key}")
    Description = "CloudWatch log group for ${each.key} CodeBuild project"
  }
}

# ============================================================
# CodeBuild Projects (one per entry in codebuild_projects)
# ============================================================

resource "aws_codebuild_project" "this" {
  for_each = var.codebuild_projects

  name          = "${var.project_name}-${var.env}-${each.key}-build"
  description   = each.value.description
  service_role  = aws_iam_role.codebuild[each.key].arn
  build_timeout = 60

  artifacts {
    type           = "S3"
    location       = aws_s3_bucket.artifacts.id
    path           = "${each.key}/"
    namespace_type = "BUILD_ID"
    packaging      = "ZIP"
  }

  environment {
    type            = each.value.environment_type
    compute_type    = each.value.compute_type
    image           = each.value.image
    privileged_mode = each.value.privileged_mode

    # Common environment variables
    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = var.region
    }

    environment_variable {
      name  = "AWS_ACCOUNT_ID"
      value = var.account_id
    }

    environment_variable {
      name  = "PROJECT_NAME"
      value = var.project_name
    }

    environment_variable {
      name  = "ENVIRONMENT"
      value = var.env
    }

    # ECR repository URI (only for projects with an ecr_repo_key)
    dynamic "environment_variable" {
      for_each = each.value.ecr_repo_key != null ? { ECR_REPOSITORY_URI = var.ecr_repository_uris[each.value.ecr_repo_key] } : {}
      content {
        name  = environment_variable.key
        value = environment_variable.value
      }
    }

    # Project-specific extra environment variables (passed from Terragrunt)
    dynamic "environment_variable" {
      for_each = lookup(var.codebuild_extra_env_vars, each.key, {})
      content {
        name  = environment_variable.key
        value = environment_variable.value
      }
    }
  }

  source {
    type      = "CODECOMMIT"
    location  = "https://git-codecommit.${var.region}.amazonaws.com/v1/repos/${var.codecommit_repo_name}"
    buildspec = each.value.buildspec
  }

  source_version = var.codebuild_source_version

  logs_config {
    cloudwatch_logs {
      status     = "ENABLED"
      group_name = aws_cloudwatch_log_group.codebuild[each.key].name
    }
  }

  tags = {
    Name        = format(local.name_fmt, "codebuild", each.key)
    Description = each.value.description
  }
}

# ============================================================
# CodeCommit -> CodeBuild auto-trigger dispatcher
#
# A tiny Lambda subscribes to CodeCommit referenceUpdated events on the
# watch branch, diffs the push, and starts the CodeBuild project whose
# source-path prefix matches a changed file. Path map is derived from
# codebuild_projects (see local.codebuild_auto_trigger_map).
# ============================================================

data "archive_file" "codebuild_dispatcher" {
  count = length(local.codebuild_auto_trigger_map) > 0 ? 1 : 0

  type        = "zip"
  source_dir  = var.codebuild_dispatcher_source_dir
  output_path = "${path.module}/codebuild_dispatcher.zip"
}

resource "aws_iam_role" "codebuild_dispatcher" {
  count = length(local.codebuild_auto_trigger_map) > 0 ? 1 : 0

  name = format(local.name_fmt, "role", "codebuild-dispatcher")

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    Name        = format(local.name_fmt, "role", "codebuild-dispatcher")
    Description = "Execution role for the CodeCommit to CodeBuild dispatcher Lambda"
  }
}

resource "aws_iam_role_policy" "codebuild_dispatcher" {
  count = length(local.codebuild_auto_trigger_map) > 0 ? 1 : 0

  name = "dispatch-codebuild"
  role = aws_iam_role.codebuild_dispatcher[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          aws_cloudwatch_log_group.codebuild_dispatcher[0].arn,
          "${aws_cloudwatch_log_group.codebuild_dispatcher[0].arn}:*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["codecommit:GetDifferences"]
        Resource = "arn:aws:codecommit:${var.region}:${var.account_id}:${var.codecommit_repo_name}"
      },
      {
        Effect = "Allow"
        Action = ["codebuild:StartBuild"]
        Resource = [
          for project_name in values(local.codebuild_auto_trigger_map) :
          "arn:aws:codebuild:${var.region}:${var.account_id}:project/${project_name}"
        ]
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "codebuild_dispatcher" {
  count = length(local.codebuild_auto_trigger_map) > 0 ? 1 : 0

  name              = "/aws/lambda/${var.project_name}-${var.env}-codebuild-dispatcher"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.cloudwatch_kms_key_arn

  tags = {
    Name        = format(local.name_fmt, "log", "codebuild-dispatcher")
    Description = "CloudWatch log group for the CodeBuild dispatcher Lambda"
  }
}

resource "aws_lambda_function" "codebuild_dispatcher" {
  count = length(local.codebuild_auto_trigger_map) > 0 ? 1 : 0

  function_name = "${var.project_name}-${var.env}-codebuild-dispatcher"
  role          = aws_iam_role.codebuild_dispatcher[0].arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 256

  filename         = data.archive_file.codebuild_dispatcher[0].output_path
  source_code_hash = data.archive_file.codebuild_dispatcher[0].output_base64sha256

  environment {
    variables = {
      WATCH_BRANCH    = replace(var.codebuild_source_version, "refs/heads/", "")
      PATH_TO_PROJECT = jsonencode(local.codebuild_auto_trigger_map)
    }
  }

  # trivy:ignore:AVD-AWS-0066 # Dispatcher is a pure control-plane trigger (no data, no PII); DLQ is overkill for a single retry
  # trivy:ignore:AVD-AWS-0158 # X-Ray tracing is overkill for a single-shot dispatcher; CloudWatch logs cover debugging
  # trivy:ignore:AVD-AWS-0136 # Managed by AWS-owned KMS key via CW Logs kms_key_id (set above)
  tags = {
    Name        = format(local.name_fmt, "lambda", "codebuild-dispatcher")
    Description = "CodeCommit push to CodeBuild auto-trigger dispatcher"
  }

  depends_on = [aws_cloudwatch_log_group.codebuild_dispatcher]
}

resource "aws_cloudwatch_event_rule" "codecommit_push" {
  count = length(local.codebuild_auto_trigger_map) > 0 ? 1 : 0

  name        = format(local.name_fmt, "evr", "codecommit-push")
  description = "Fires on every CodeCommit push to the watched branch"

  event_pattern = jsonencode({
    source        = ["aws.codecommit"]
    "detail-type" = ["CodeCommit Repository State Change"]
    resources     = ["arn:aws:codecommit:${var.region}:${var.account_id}:${var.codecommit_repo_name}"]
    detail = {
      event         = ["referenceUpdated"]
      referenceType = ["branch"]
      # CodeCommit emits the bare branch name in detail.referenceName,
      # e.g. "main" - not the full ref "refs/heads/main" used for
      # CodeBuild's source_version. Strip the prefix.
      referenceName = [replace(var.codebuild_source_version, "refs/heads/", "")]
    }
  })

  tags = {
    Name        = format(local.name_fmt, "evr", "codecommit-push")
    Description = "CodeCommit referenceUpdated events routed to the dispatcher Lambda"
  }
}

resource "aws_cloudwatch_event_target" "codebuild_dispatcher" {
  count = length(local.codebuild_auto_trigger_map) > 0 ? 1 : 0

  rule      = aws_cloudwatch_event_rule.codecommit_push[0].name
  target_id = "codebuild-dispatcher"
  arn       = aws_lambda_function.codebuild_dispatcher[0].arn
}

resource "aws_lambda_permission" "eventbridge_invoke_dispatcher" {
  count = length(local.codebuild_auto_trigger_map) > 0 ? 1 : 0

  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.codebuild_dispatcher[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.codecommit_push[0].arn
}
