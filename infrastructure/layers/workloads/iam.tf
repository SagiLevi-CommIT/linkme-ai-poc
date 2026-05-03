data "aws_iam_policy_document" "task_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

resource "aws_iam_role" "task" {
  for_each = var.enable_workloads ? var.workloads_task_config : {}

  name               = format(local.name_fmt, "role", "workloads-${each.value.name}")
  assume_role_policy = data.aws_iam_policy_document.task_assume.json

  tags = {
    Name        = format(local.name_fmt, "role", "workloads-${each.value.name}")
    Description = "Task role for ${each.value.name}"
  }
}

# ---- cache-service inline policy ----
data "aws_iam_policy_document" "cache_service_inline" {
  count = var.enable_workloads ? 1 : 0

  statement {
    sid       = "SQSConsumeIncoming"
    effect    = "Allow"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [var.incoming_queue_arn]
  }

  statement {
    sid       = "SQSSendAiProcessing"
    effect    = "Allow"
    actions   = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
    resources = [var.ai_processing_queue_arn]
  }

  statement {
    sid       = "DDBCacheResults"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem", "dynamodb:Query"]
    resources = concat([var.results_table_arn], var.phase1_ddb_table_arns)
  }

  statement {
    sid       = "SageMakerInvoke"
    effect    = "Allow"
    actions   = ["sagemaker:InvokeEndpoint"]
    resources = [var.sagemaker_endpoint_arn]
  }

  statement {
    sid       = "CloudWatchEMF"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:/ecs/${var.project_name}/${var.env}/*"]
  }

  dynamic "statement" {
    for_each = var.message_lifecycle_log_group_arn != "" ? [1] : []
    content {
      sid    = "MessageLifecycleLogs"
      effect = "Allow"
      actions = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams",
      ]
      resources = [
        var.message_lifecycle_log_group_arn,
        "${var.message_lifecycle_log_group_arn}:*",
      ]
    }
  }
}

resource "aws_iam_role_policy" "cache_service" {
  count = var.enable_workloads ? 1 : 0

  name   = "inline"
  role   = aws_iam_role.task["cache_service"].id
  policy = data.aws_iam_policy_document.cache_service_inline[0].json
}

# ---- llm-service inline policy ----
data "aws_iam_policy_document" "llm_service_inline" {
  count = var.enable_workloads ? 1 : 0

  statement {
    sid       = "SQSConsumeAiProcessing"
    effect    = "Allow"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [var.ai_processing_queue_arn]
  }

  statement {
    sid       = "DDBResultsWrite"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:BatchWriteItem", "dynamodb:GetItem", "dynamodb:Query"]
    resources = concat([var.results_table_arn], var.phase1_ddb_table_arns)
  }

  statement {
    sid       = "BedrockInvoke"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = concat(var.bedrock_model_arns, var.bedrock_inference_profile_arns)
  }

  statement {
    sid       = "BedrockKBRetrieve"
    effect    = "Allow"
    actions   = ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"]
    resources = ["arn:aws:bedrock:${var.region}:${var.account_id}:knowledge-base/${var.knowledge_base_id}"]
  }

  statement {
    sid       = "SageMakerInvoke"
    effect    = "Allow"
    actions   = ["sagemaker:InvokeEndpoint"]
    resources = [var.sagemaker_endpoint_arn]
  }

  statement {
    sid       = "CloudWatchEMF"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:/ecs/${var.project_name}/${var.env}/*"]
  }

  dynamic "statement" {
    for_each = var.message_lifecycle_log_group_arn != "" ? [1] : []
    content {
      sid    = "MessageLifecycleLogs"
      effect = "Allow"
      actions = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams",
      ]
      resources = [
        var.message_lifecycle_log_group_arn,
        "${var.message_lifecycle_log_group_arn}:*",
      ]
    }
  }
}

resource "aws_iam_role_policy" "llm_service" {
  count = var.enable_workloads ? 1 : 0

  name   = "inline"
  role   = aws_iam_role.task["llm_service"].id
  policy = data.aws_iam_policy_document.llm_service_inline[0].json
}

# ---- messages-pusher inline policy ----
data "aws_iam_policy_document" "messages_pusher_inline" {
  count = var.enable_workloads ? 1 : 0

  statement {
    sid       = "S3ReadInputMessages"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [var.input_messages_bucket_arn, "${var.input_messages_bucket_arn}/*"]
  }

  statement {
    sid       = "SQSSendIncoming"
    effect    = "Allow"
    actions   = ["sqs:SendMessage", "sqs:SendMessageBatch", "sqs:GetQueueAttributes"]
    resources = [var.incoming_queue_arn]
  }

  statement {
    sid       = "CloudWatchEMF"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:/ecs/${var.project_name}/${var.env}/*"]
  }
}

resource "aws_iam_role_policy" "messages_pusher" {
  count = var.enable_workloads ? 1 : 0

  name   = "inline"
  role   = aws_iam_role.task["messages_pusher"].id
  policy = data.aws_iam_policy_document.messages_pusher_inline[0].json
}
