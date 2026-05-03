locals {
  poc_metrics_namespace = "Linkme/PoC"
  poc_report_dashboard  = "Linkme PoC Report"
}

# Supplier spec: single log group for message.lifecycle JSON lines (30-day retention).
resource "aws_cloudwatch_log_group" "message_lifecycle" {
  count             = local.enable_messaging ? 1 : 0
  name              = "/linkme/poc/message-lifecycle"
  retention_in_days = 30

  tags = {
    Name        = "/linkme/poc/message-lifecycle"
    Description = "PoC message.lifecycle JSON logs for client reporting"
  }
}

# Metric filter 1: count by status + path (default_value 0 per spec).
resource "aws_cloudwatch_log_metric_filter" "messages_processed" {
  count          = local.enable_messaging ? 1 : 0
  name           = "linkme-poc-messages-processed"
  log_group_name = aws_cloudwatch_log_group.message_lifecycle[0].name
  pattern        = "{ $.event = \"message.lifecycle\" }"

  metric_transformation {
    name          = "MessagesProcessed"
    namespace     = local.poc_metrics_namespace
    value         = "1"
    default_value = 0
    dimensions = {
      status = "$.status"
      path   = "$.path"
    }
  }
}

# Metric filter 2: success-only latency distribution by path (no default_value per spec).
resource "aws_cloudwatch_log_metric_filter" "end_to_end_latency" {
  count          = local.enable_messaging ? 1 : 0
  name           = "linkme-poc-end-to-end-latency"
  log_group_name = aws_cloudwatch_log_group.message_lifecycle[0].name
  pattern        = "{ $.event = \"message.lifecycle\" && $.status = \"success\" }"

  metric_transformation {
    name      = "EndToEndLatencyMs"
    namespace = local.poc_metrics_namespace
    value     = "$.total_latency_ms"
    dimensions = {
      path = "$.path"
    }
  }
}

# Supplier dashboard (7 widgets) — metrics from log filters above.
resource "aws_cloudwatch_dashboard" "poc_report" {
  count = local.enable_messaging ? 1 : 0

  dashboard_name = local.poc_report_dashboard

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 8
        height = 6
        properties = {
          title                    = "End-to-end completion rate"
          region                   = var.region
          view                     = "singleValue"
          period                   = 60
          setPeriodToTimeRange     = true
          singleValueFullPrecision = false
          metrics = [
            [{ "expression" : "IF(mTot>0, 100*mOk/mTot, 0)", "label" : "Success %", "id" : "e1" }],
            [{ "expression" : "SUM(SEARCH('{${local.poc_metrics_namespace},MetricName,MessagesProcessed,status} MetricName=\"MessagesProcessed\" status=\"success\"', 'Sum', 60))", "id" : "mOk", "visible" : false }],
            [{ "expression" : "SUM(SEARCH('{${local.poc_metrics_namespace},MetricName,MessagesProcessed,status} MetricName=\"MessagesProcessed\"', 'Sum', 60))", "id" : "mTot", "visible" : false }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 0
        width  = 8
        height = 6
        properties = {
          title                = "p95 latency (overall, success)"
          region               = var.region
          view                 = "singleValue"
          period               = 60
          setPeriodToTimeRange = true
          metrics = [
            [{ "expression" : "MAX(REMOVE_EMPTY(SEARCH('{${local.poc_metrics_namespace}} MetricName=\"EndToEndLatencyMs\"', 'p95', 60)))", "label" : "p95 (max across paths)" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 0
        width  = 8
        height = 6
        properties = {
          title                = "p99 latency (overall, success)"
          region               = var.region
          view                 = "singleValue"
          period               = 60
          setPeriodToTimeRange = true
          metrics = [
            [{ "expression" : "MAX(REMOVE_EMPTY(SEARCH('{${local.poc_metrics_namespace}} MetricName=\"EndToEndLatencyMs\"', 'p99', 60)))", "label" : "p99 (max across paths)" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 24
        height = 6
        properties = {
          title  = "Messages per second (sum(MessagesProcessed)/60)"
          region = var.region
          view   = "timeSeries"
          period = 60
          metrics = [
            [{ "expression" : "FILL(mALL,0)/60", "label" : "msg/s", "id" : "e1" }],
            [{ "expression" : "SUM(SEARCH('{${local.poc_metrics_namespace},MetricName,MessagesProcessed,path,status} MetricName=\"MessagesProcessed\"', 'Sum', 60))", "id" : "mALL", "visible" : false }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 24
        height = 6
        properties = {
          title  = "p95 latency by path (success only)"
          region = var.region
          view   = "timeSeries"
          stat   = "p95"
          period = 60
          metrics = [
            [{ "expression" : "(mE+mS)/2", "label" : "p95 cache hits (avg exact+semantic)", "id" : "eHit" }],
            ["${local.poc_metrics_namespace}", "EndToEndLatencyMs", "path", "cache_hit_exact", { "id" : "mE", "visible" : false, "stat" : "p95" }],
            ["...", "EndToEndLatencyMs", "path", "cache_hit_semantic", { "id" : "mS", "visible" : false, "stat" : "p95" }],
            ["...", "EndToEndLatencyMs", "path", "cache_miss", { "label" : "p95 cache_miss", "stat" : "p95" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 18
        width  = 24
        height = 6
        properties = {
          title   = "Message count by path (MessagesProcessed sum)"
          region  = var.region
          view    = "timeSeries"
          stacked = true
          stat    = "Sum"
          period  = 60
          metrics = [
            ["${local.poc_metrics_namespace}", "MessagesProcessed", "path", "cache_hit_exact", { "label" : "cache_hit_exact" }],
            ["...", "MessagesProcessed", "path", "cache_hit_semantic", { "label" : "cache_hit_semantic" }],
            ["...", "MessagesProcessed", "path", "cache_miss", { "label" : "cache_miss" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 24
        width  = 12
        height = 6
        properties = {
          title                = "Cache hit rate — exact / all"
          region               = var.region
          view                 = "singleValue"
          period               = 60
          setPeriodToTimeRange = true
          metrics = [
            [{ "expression" : "IF(mT>0, 100*mE/mT, 0)", "label" : "Exact %", "id" : "e1" }],
            [{ "expression" : "SUM(SEARCH('{${local.poc_metrics_namespace},MetricName,MessagesProcessed,path,status} MetricName=\"MessagesProcessed\" path=\"cache_hit_exact\"', 'Sum', 60))", "id" : "mE", "visible" : false }],
            [{ "expression" : "SUM(SEARCH('{${local.poc_metrics_namespace},MetricName,MessagesProcessed,path,status} MetricName=\"MessagesProcessed\"', 'Sum', 60))", "id" : "mT", "visible" : false }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 24
        width  = 12
        height = 6
        properties = {
          title                = "Cache hit rate — semantic / all"
          region               = var.region
          view                 = "singleValue"
          period               = 60
          setPeriodToTimeRange = true
          metrics = [
            [{ "expression" : "IF(mT>0, 100*mS/mT, 0)", "label" : "Semantic %", "id" : "e1" }],
            [{ "expression" : "SUM(SEARCH('{${local.poc_metrics_namespace},MetricName,MessagesProcessed,path,status} MetricName=\"MessagesProcessed\" path=\"cache_hit_semantic\"', 'Sum', 60))", "id" : "mS", "visible" : false }],
            [{ "expression" : "SUM(SEARCH('{${local.poc_metrics_namespace},MetricName,MessagesProcessed,path,status} MetricName=\"MessagesProcessed\"', 'Sum', 60))", "id" : "mT", "visible" : false }]
          ]
        }
      }
    ]
  })
}

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
  threshold           = 10000
  alarm_description   = "End-to-end p95 latency (message.lifecycle success, max across paths) exceeds 10 seconds"
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "p95all"
    expression  = "MAX(REMOVE_EMPTY(SEARCH('{${local.poc_metrics_namespace}} MetricName=\"EndToEndLatencyMs\"', 'p95', 60)))"
    label       = "p95 EndToEndLatencyMs"
    return_data = true
  }

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
