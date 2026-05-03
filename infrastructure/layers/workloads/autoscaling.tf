resource "aws_appautoscaling_target" "cache_service" {
  count = var.enable_workloads && var.enable_autoscaling ? 1 : 0

  max_capacity       = var.workloads_task_config.cache_service.max_capacity
  min_capacity       = var.workloads_task_config.cache_service.min_capacity
  resource_id        = "service/${var.ecs_cluster_name}/${aws_ecs_service.cache_service[0].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cache_service_sqs_depth" {
  count = var.enable_workloads && var.enable_autoscaling ? 1 : 0

  name               = format(local.name_fmt, "asp", "cache-sqs-depth")
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.cache_service[0].resource_id
  scalable_dimension = aws_appautoscaling_target.cache_service[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.cache_service[0].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.workloads_task_config.cache_service.sqs_target_msgs
    scale_in_cooldown  = 60
    scale_out_cooldown = 30

    customized_metric_specification {
      metric_name = "ApproximateNumberOfMessagesVisible"
      namespace   = "AWS/SQS"
      statistic   = "Average"

      dimensions {
        name  = "QueueName"
        value = reverse(split("/", var.incoming_queue_arn))[0]
      }
    }
  }
}

resource "aws_appautoscaling_target" "llm_service" {
  count = var.enable_workloads && var.enable_autoscaling ? 1 : 0

  max_capacity       = var.workloads_task_config.llm_service.max_capacity
  min_capacity       = var.workloads_task_config.llm_service.min_capacity
  resource_id        = "service/${var.ecs_cluster_name}/${aws_ecs_service.llm_service[0].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "llm_service_sqs_depth" {
  count = var.enable_workloads && var.enable_autoscaling ? 1 : 0

  name               = format(local.name_fmt, "asp", "llm-sqs-depth")
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.llm_service[0].resource_id
  scalable_dimension = aws_appautoscaling_target.llm_service[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.llm_service[0].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.workloads_task_config.llm_service.sqs_target_msgs
    scale_in_cooldown  = 60
    scale_out_cooldown = 30

    customized_metric_specification {
      metric_name = "ApproximateNumberOfMessagesVisible"
      namespace   = "AWS/SQS"
      statistic   = "Average"

      dimensions {
        name  = "QueueName"
        value = reverse(split("/", var.ai_processing_queue_arn))[0]
      }
    }
  }
}
