# ================================================================
# SQS - incoming (standard) - messages-pusher to cache-service
# ================================================================

resource "aws_sqs_queue" "incoming_dlq" {
  count = local.enable_messaging ? 1 : 0

  name                       = "sqs-${var.project_name}-${var.env}-incoming-dlq"
  message_retention_seconds  = var.sqs_config.message_retention_seconds
  sqs_managed_sse_enabled    = true
  receive_wait_time_seconds  = 20
  visibility_timeout_seconds = var.sqs_config.incoming_visibility_timeout

  tags = {
    Name        = "sqs-${var.project_name}-${var.env}-incoming-dlq"
    Description = "DLQ for incoming standard queue"
  }
}

resource "aws_sqs_queue" "incoming" {
  count = local.enable_messaging ? 1 : 0

  name                       = "sqs-${var.project_name}-${var.env}-incoming"
  visibility_timeout_seconds = var.sqs_config.incoming_visibility_timeout
  message_retention_seconds  = var.sqs_config.message_retention_seconds
  sqs_managed_sse_enabled    = true
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.incoming_dlq[0].arn
    maxReceiveCount     = var.sqs_config.dlq_max_receive_count
  })

  tags = {
    Name        = "sqs-${var.project_name}-${var.env}-incoming"
    Description = "Messages Pusher to Cache Service standard queue"
  }
}

resource "aws_sqs_queue_redrive_allow_policy" "incoming_dlq" {
  count = local.enable_messaging ? 1 : 0

  queue_url = aws_sqs_queue.incoming_dlq[0].id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.incoming[0].arn]
  })
}

# ================================================================
# SQS - ai-processing.fifo - cache-service miss to llm-service (per-lead ordering)
# ================================================================

resource "aws_sqs_queue" "ai_processing_dlq" {
  count = local.enable_messaging ? 1 : 0

  name                        = "sqs-${var.project_name}-${var.env}-ai-processing-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = var.sqs_config.message_retention_seconds
  sqs_managed_sse_enabled     = true
  receive_wait_time_seconds   = 20
  visibility_timeout_seconds  = var.sqs_config.ai_processing_visibility_timeout

  tags = {
    Name        = "sqs-${var.project_name}-${var.env}-ai-processing-dlq.fifo"
    Description = "DLQ for ai-processing FIFO queue"
  }
}

resource "aws_sqs_queue" "ai_processing" {
  count = local.enable_messaging ? 1 : 0

  name                        = "sqs-${var.project_name}-${var.env}-ai-processing.fifo"
  fifo_queue                  = true
  fifo_throughput_limit       = "perMessageGroupId"
  deduplication_scope         = "messageGroup"
  content_based_deduplication = false
  visibility_timeout_seconds  = var.sqs_config.ai_processing_visibility_timeout
  message_retention_seconds   = var.sqs_config.message_retention_seconds
  sqs_managed_sse_enabled     = true
  receive_wait_time_seconds   = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ai_processing_dlq[0].arn
    maxReceiveCount     = var.sqs_config.dlq_max_receive_count
  })

  tags = {
    Name        = "sqs-${var.project_name}-${var.env}-ai-processing.fifo"
    Description = "Cache miss to LLM Service per-lead FIFO queue"
  }
}

resource "aws_sqs_queue_redrive_allow_policy" "ai_processing_dlq" {
  count = local.enable_messaging ? 1 : 0

  queue_url = aws_sqs_queue.ai_processing_dlq[0].id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.ai_processing[0].arn]
  })
}
