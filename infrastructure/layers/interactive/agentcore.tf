resource "aws_iam_role" "agentcore" {
  count = var.enable_agentcore_runtime ? 1 : 0

  name               = format(local.name_fmt, "role", "agentcore-runtime")
  assume_role_policy = data.aws_iam_policy_document.agentcore_assume[0].json

  tags = {
    Name        = format(local.name_fmt, "role", "agentcore-runtime")
    Description = "Execution role for the Bedrock AgentCore Runtime Phase 1 agent"
  }
}

data "aws_iam_policy_document" "agentcore_assume" {
  count = var.enable_agentcore_runtime ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

data "aws_iam_policy_document" "agentcore_inline" {
  count = var.enable_agentcore_runtime ? 1 : 0

  statement {
    sid     = "BedrockInvoke"
    effect  = "Allow"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:aws:bedrock:${var.region}::foundation-model/anthropic.claude-sonnet-4-6",
      "arn:aws:bedrock:${var.region}::foundation-model/anthropic.claude-opus-4-6-v1",
      "arn:aws:bedrock:${var.region}:${var.account_id}:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "arn:aws:bedrock:${var.region}:${var.account_id}:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
    ]
  }

  statement {
    sid       = "BedrockKBRetrieve"
    effect    = "Allow"
    actions   = ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"]
    resources = ["arn:aws:bedrock:${var.region}:${var.account_id}:knowledge-base/${var.knowledge_base_id}"]
  }

  statement {
    sid       = "BedrockKBIngestion"
    effect    = "Allow"
    actions   = ["bedrock:StartIngestionJob", "bedrock:GetIngestionJob", "bedrock:ListIngestionJobs"]
    resources = ["arn:aws:bedrock:${var.region}:${var.account_id}:knowledge-base/${var.knowledge_base_id}"]
  }

  statement {
    sid       = "DDBProfileMessageCache"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem"]
    resources = [for t in aws_dynamodb_table.this : t.arn]
  }

  statement {
    sid     = "S3ObjectAccess"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [
      var.raw_uploads_bucket_arn,
      "${var.raw_uploads_bucket_arn}/*",
      "arn:aws:s3:::${var.kb_source_bucket_name}",
      "arn:aws:s3:::${var.kb_source_bucket_name}/*",
    ]
  }

  statement {
    sid       = "AgentCoreWorkloadIdentity"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:GetWorkloadAccessToken", "bedrock-agentcore:GetWorkloadAccessTokenForJWT", "bedrock-agentcore:GetWorkloadAccessTokenForUserId"]
    resources = ["*"]
  }

  statement {
    sid       = "CloudWatchLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/bedrock-agentcore/*"]
  }

  statement {
    sid       = "ECRPull"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "agentcore_inline" {
  count = var.enable_agentcore_runtime ? 1 : 0

  name   = "inline"
  role   = aws_iam_role.agentcore[0].id
  policy = data.aws_iam_policy_document.agentcore_inline[0].json
}

resource "aws_bedrockagentcore_agent_runtime" "phase1" {
  count = var.enable_agentcore_runtime ? 1 : 0

  agent_runtime_name = var.agentcore_runtime_config.runtime_name
  role_arn           = aws_iam_role.agentcore[0].arn
  description        = "Phase 1 conversational agent for creator setup Strands SDK ARM64 container"

  agent_runtime_artifact {
    container_configuration {
      container_uri = local.agentcore_image_uri
    }
  }

  network_configuration {
    network_mode = var.agentcore_runtime_config.network_mode
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  environment_variables = {
    DDB_PROFILES_TABLE = aws_dynamodb_table.this["profiles"].name
    DDB_MESSAGES_TABLE = aws_dynamodb_table.this["messages"].name
    DDB_CACHE_TABLE    = aws_dynamodb_table.this["cache"].name
    KB_ID              = var.knowledge_base_id
    KB_SOURCE_BUCKET   = var.kb_source_bucket_name
    RAW_UPLOADS_BUCKET = var.raw_uploads_bucket_name
    AWS_REGION         = var.region
  }

  tags = {
    Name        = var.agentcore_runtime_config.runtime_name
    Description = "LinkMe POC Phase 1 AgentCore Runtime"
  }

  depends_on = [aws_iam_role_policy.agentcore_inline]
}
