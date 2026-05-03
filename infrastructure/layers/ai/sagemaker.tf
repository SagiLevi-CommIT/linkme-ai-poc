# SageMaker real-time endpoint for semantic-cache embeddings.
#
# Runs Hugging Face Text Embeddings Inference (TEI) - a Rust server with
# server-side dynamic batching that delivers 20-50x the throughput of the
# default HF Inference Toolkit on the same hardware. See
# project_tei_embedding_win memory note for the burst measurements.
#
# The image is built by the tei-embedding CodeBuild project (see
# src/tei_embedding/) from a thin wrapper over the upstream GHCR image.
# The wrapper ignores the "serve" positional arg that SageMaker passes
# to inference containers (TEI's router rejects unknown positionals).
# Wrapper tag format: <TEI_BASE_TAG>-sm-<git-sha12>, where TEI_BASE_TAG
# is one of:
#   - turing-1.6 : compute cap 7.5 (T4   - g4dn family)
#   - 86-1.6     : compute cap 8.6 (A10G - g5 family)
locals {
  sagemaker_tei_ecr_uri   = "${var.account_id}.dkr.ecr.${var.region}.amazonaws.com/${var.project_name}-${var.env}-tei-embedding"
  sagemaker_tei_image_uri = "${local.sagemaker_tei_ecr_uri}:${var.sagemaker_embedding.image_tag}"
}

resource "aws_sagemaker_model" "tei" {
  count = local.enable_sagemaker ? 1 : 0

  name               = var.sagemaker_embedding.model_name
  execution_role_arn = aws_iam_role.sagemaker[0].arn

  primary_container {
    image = local.sagemaker_tei_image_uri

    environment = {
      MODEL_ID                = var.sagemaker_embedding.huggingface_model
      MAX_BATCH_TOKENS        = "65536"
      MAX_CONCURRENT_REQUESTS = "512"
      MAX_CLIENT_BATCH_SIZE   = "128"
      PORT                    = "8080"
    }
  }

  tags = {
    Name        = var.sagemaker_embedding.model_name
    Description = "SageMaker TEI model for bge-base-en-v1.5 with server-side dynamic batching"
  }
}

resource "aws_sagemaker_endpoint_configuration" "tei" {
  count = local.enable_sagemaker ? 1 : 0

  name = var.sagemaker_embedding.config_name

  production_variants {
    variant_name           = "primary"
    model_name             = aws_sagemaker_model.tei[0].name
    initial_instance_count = var.sagemaker_embedding.initial_count
    instance_type          = var.sagemaker_embedding.instance_type
  }

  tags = {
    Name        = var.sagemaker_embedding.config_name
    Description = "SageMaker endpoint config for TEI on T4 GPU g4dn.xlarge"
  }
}

# Real-time endpoint. The operator uses task sm:up and task sm:down to
# bring the endpoint in and out of service during test windows, so
# ignore drift on endpoint_config_name.
resource "aws_sagemaker_endpoint" "embedding" {
  count = local.enable_sagemaker ? 1 : 0

  name                 = var.sagemaker_embedding.endpoint_name
  endpoint_config_name = aws_sagemaker_endpoint_configuration.tei[0].name

  tags = {
    Name        = var.sagemaker_embedding.endpoint_name
    Description = "SageMaker real-time endpoint for bge-base-en-v1.5 semantic cache embeddings"
  }

  lifecycle {
    ignore_changes = [endpoint_config_name]
  }
}

# ================================================================
# Application Auto Scaling on the endpoint variant (1 baseline, 2 burst).
# Target tracking on SageMakerVariantInvocationsPerInstance triggers the
# scale-out under burst load.
# ================================================================

resource "aws_appautoscaling_target" "sagemaker_embedding" {
  count = local.enable_sagemaker && var.sagemaker_embedding.enable_autoscaling ? 1 : 0

  min_capacity       = var.sagemaker_embedding.autoscaling_min
  max_capacity       = var.sagemaker_embedding.autoscaling_max
  resource_id        = "endpoint/${aws_sagemaker_endpoint.embedding[0].name}/variant/primary"
  scalable_dimension = "sagemaker:variant:DesiredInstanceCount"
  service_namespace  = "sagemaker"
}

resource "aws_appautoscaling_policy" "sagemaker_embedding_invocations" {
  count = local.enable_sagemaker && var.sagemaker_embedding.enable_autoscaling ? 1 : 0

  name               = format(local.name_fmt, "asp", "sagemaker-embedding-invocations")
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.sagemaker_embedding[0].resource_id
  scalable_dimension = aws_appautoscaling_target.sagemaker_embedding[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.sagemaker_embedding[0].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.sagemaker_embedding.autoscaling_target_invocations_per_instance
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "SageMakerVariantInvocationsPerInstance"
    }
  }
}
