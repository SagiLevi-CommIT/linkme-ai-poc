resource "aws_cloudwatch_dashboard" "simulator" {
  count = local.enable_messaging ? 1 : 0

  dashboard_name = var.simulator_dashboard_name

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6,
        properties = {
          title  = "SQS Queue Depth",
          region = var.region,
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.incoming[0].name, { label = "incoming" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.ai_processing[0].name, { label = "ai-processing.fifo" }]
          ],
          view = "timeSeries", stat = "Maximum", period = 60
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6,
        properties = {
          title  = "Oldest Message Age",
          region = var.region,
          metrics = [
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", aws_sqs_queue.incoming[0].name],
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", aws_sqs_queue.ai_processing[0].name]
          ],
          view = "timeSeries", stat = "Maximum", period = 60
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6,
        properties = {
          title  = "DLQ Depth",
          region = var.region,
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.incoming_dlq[0].name, { label = "incoming-dlq" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.ai_processing_dlq[0].name, { label = "ai-processing-dlq.fifo" }]
          ],
          view = "timeSeries", stat = "Maximum", period = 60
        }
      }
    ]
  })
}

resource "aws_cloudwatch_metric_alarm" "incoming_dlq_messages" {
  count = local.enable_messaging ? 1 : 0

  alarm_name          = "cw-${var.project_name}-${var.env}-incoming-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "Incoming DLQ has messages investigate failing cache-service deliveries"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.incoming_dlq[0].name
  }

  tags = {
    Name = "cw-${var.project_name}-${var.env}-incoming-dlq-messages"
  }
}

resource "aws_cloudwatch_metric_alarm" "ai_processing_dlq_messages" {
  count = local.enable_messaging ? 1 : 0

  alarm_name          = "cw-${var.project_name}-${var.env}-ai-processing-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "AI Processing FIFO DLQ has messages investigate failing llm-service invocations"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.ai_processing_dlq[0].name
  }

  tags = {
    Name = "cw-${var.project_name}-${var.env}-ai-processing-dlq-messages"
  }
}

resource "aws_cloudwatch_metric_alarm" "incoming_queue_depth" {
  count = local.enable_messaging ? 1 : 0

  alarm_name          = "cw-${var.project_name}-${var.env}-incoming-queue-depth"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 900
  alarm_description   = "Incoming queue oldest message age exceeds 15 minutes"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.incoming[0].name
  }

  tags = {
    Name = "cw-${var.project_name}-${var.env}-incoming-queue-depth"
  }
}

resource "aws_cloudwatch_metric_alarm" "ai_processing_queue_depth" {
  count = local.enable_messaging ? 1 : 0

  alarm_name          = "cw-${var.project_name}-${var.env}-ai-processing-queue-depth"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 900
  alarm_description   = "AI processing FIFO oldest message age exceeds 15 minutes"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.ai_processing[0].name
  }

  tags = {
    Name = "cw-${var.project_name}-${var.env}-ai-processing-queue-depth"
  }
}

resource "aws_cloudwatch_metric_alarm" "e2e_latency_p95" {
  count = local.enable_messaging ? 1 : 0

  alarm_name          = "cw-${var.project_name}-${var.env}-e2e-latency-p95"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "E2ELatencyMs"
  namespace           = "LinkMe/POC/Simulator"
  period              = 60
  extended_statistic  = "p95"
  threshold           = 10000
  alarm_description   = "End-to-end p95 latency exceeds 10 seconds"
  treat_missing_data  = "notBreaching"

  tags = {
    Name = "cw-${var.project_name}-${var.env}-e2e-latency-p95"
  }
}

resource "aws_cloudwatch_metric_alarm" "results_write_throttles" {
  count = local.enable_messaging ? 1 : 0

  alarm_name          = "cw-${var.project_name}-${var.env}-results-write-throttles"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "WriteThrottleEvents"
  namespace           = "AWS/DynamoDB"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "DDB Results table write throttles exceed 0"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TableName = aws_dynamodb_table.results[0].name
  }

  tags = {
    Name = "cw-${var.project_name}-${var.env}-results-write-throttles"
  }
}
