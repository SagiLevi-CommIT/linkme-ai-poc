# ================================================================
# Knowledge Base execution role
# ================================================================

data "aws_iam_policy_document" "kb_assume" {
  count = local.enable_knowledge_base ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

resource "aws_iam_role" "kb" {
  count = local.enable_knowledge_base ? 1 : 0

  name               = format(local.name_fmt, "role", "kb")
  assume_role_policy = data.aws_iam_policy_document.kb_assume[0].json

  tags = {
    Name        = format(local.name_fmt, "role", "kb")
    Description = "IAM role for Bedrock Knowledge Base ingestion"
  }
}

data "aws_iam_policy_document" "kb_s3_source" {
  count = local.enable_knowledge_base ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.kb_source.arn, "${aws_s3_bucket.kb_source.arn}/*"]
  }
}

resource "aws_iam_role_policy" "kb_s3_source" {
  count = local.enable_knowledge_base ? 1 : 0

  name   = "s3-kb-source"
  role   = aws_iam_role.kb[0].id
  policy = data.aws_iam_policy_document.kb_s3_source[0].json
}

data "aws_iam_policy_document" "kb_s3_vectors" {
  count = local.enable_knowledge_base ? 1 : 0

  statement {
    effect = "Allow"
    actions = [
      "s3vectors:DeleteVectors",
      "s3vectors:GetVectors",
      "s3vectors:ListVectors",
      "s3vectors:PutVectors",
      "s3vectors:QueryVectors",
    ]
    resources = [
      "arn:aws:s3vectors:${var.region}:${var.account_id}:bucket/${aws_s3vectors_vector_bucket.this[0].vector_bucket_name}",
      "arn:aws:s3vectors:${var.region}:${var.account_id}:bucket/${aws_s3vectors_vector_bucket.this[0].vector_bucket_name}/*",
    ]
  }
}

resource "aws_iam_role_policy" "kb_s3_vectors" {
  count = local.enable_knowledge_base ? 1 : 0

  name   = "s3-vectors"
  role   = aws_iam_role.kb[0].id
  policy = data.aws_iam_policy_document.kb_s3_vectors[0].json
}

data "aws_iam_policy_document" "kb_embedding" {
  count = local.enable_knowledge_base ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = [var.embedding_model_arn]
  }
}

resource "aws_iam_role_policy" "kb_embedding" {
  count = local.enable_knowledge_base ? 1 : 0

  name   = "bedrock-embedding"
  role   = aws_iam_role.kb[0].id
  policy = data.aws_iam_policy_document.kb_embedding[0].json
}

# ================================================================
# Agent (preview path) execution role
# ================================================================

data "aws_iam_policy_document" "agent_assume" {
  count = local.enable_agent ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

resource "aws_iam_role" "agent" {
  count = local.enable_agent ? 1 : 0

  name               = format(local.name_fmt, "role", "agent")
  assume_role_policy = data.aws_iam_policy_document.agent_assume[0].json

  tags = {
    Name        = format(local.name_fmt, "role", "agent")
    Description = "IAM role for Bedrock Agent preview path"
  }
}

data "aws_iam_policy_document" "agent_model" {
  count = local.enable_agent ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:aws:bedrock:${var.region}::foundation-model/${var.agent_foundation_model}",
      "arn:aws:bedrock:${var.region}:${var.account_id}:inference-profile/*",
    ]
  }
}

resource "aws_iam_role_policy" "agent_model" {
  count = local.enable_agent ? 1 : 0

  name   = "bedrock-model"
  role   = aws_iam_role.agent[0].id
  policy = data.aws_iam_policy_document.agent_model[0].json
}

data "aws_iam_policy_document" "agent_kb" {
  count = local.enable_agent && local.enable_knowledge_base ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"]
    resources = [aws_bedrockagent_knowledge_base.this[0].arn]
  }
}

resource "aws_iam_role_policy" "agent_kb" {
  count = local.enable_agent && local.enable_knowledge_base ? 1 : 0

  name   = "bedrock-kb"
  role   = aws_iam_role.agent[0].id
  policy = data.aws_iam_policy_document.agent_kb[0].json
}

data "aws_iam_policy_document" "agent_s3" {
  count = local.enable_agent ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.kb_source.arn, "${aws_s3_bucket.kb_source.arn}/*",
      aws_s3_bucket.raw_uploads.arn, "${aws_s3_bucket.raw_uploads.arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "agent_s3" {
  count = local.enable_agent ? 1 : 0

  name   = "s3-kb-data"
  role   = aws_iam_role.agent[0].id
  policy = data.aws_iam_policy_document.agent_s3[0].json
}

# ================================================================
# SageMaker execution role (for embedding endpoint)
# ================================================================

data "aws_iam_policy_document" "sagemaker_assume" {
  count = local.enable_sagemaker ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

resource "aws_iam_role" "sagemaker" {
  count = local.enable_sagemaker ? 1 : 0

  name               = format(local.name_fmt, "role", "sagemaker-embedding")
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume[0].json

  tags = {
    Name        = format(local.name_fmt, "role", "sagemaker-embedding")
    Description = "Execution role for the bge-base-en-v1.5 embedding endpoint"
  }
}

# Minimal permissions the SageMaker-managed inference container needs at
# runtime: pull the TEI image from our ECR and ship logs to CloudWatch.
# TEI downloads the model weights from the public Hugging Face Hub at
# container start, so no S3 permissions are needed for this POC.
data "aws_iam_policy_document" "sagemaker_inference" {
  count = local.enable_sagemaker ? 1 : 0

  statement {
    sid       = "EcrLogin"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPullTEI"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [
      "arn:aws:ecr:${var.region}:${var.account_id}:repository/${var.project_name}-${var.env}-tei-embedding",
    ]
  }

  # logs:CreateLogGroup and logs:DescribeLogStreams operate on the log
  # group resource. logs:CreateLogStream and logs:PutLogEvents operate
  # on log streams inside a group, so they need the :log-stream:* ARN
  # suffix - a log-group-level ARN is not sufficient for those actions.
  statement {
    sid    = "CloudWatchLogGroup"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:DescribeLogStreams",
    ]
    resources = [
      "arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/sagemaker/Endpoints/*",
    ]
  }

  statement {
    sid    = "CloudWatchLogStream"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/sagemaker/Endpoints/*:log-stream:*",
    ]
  }
}

resource "aws_iam_role_policy" "sagemaker_inference" {
  count = local.enable_sagemaker ? 1 : 0

  name   = "inference-runtime"
  role   = aws_iam_role.sagemaker[0].id
  policy = data.aws_iam_policy_document.sagemaker_inference[0].json
}
