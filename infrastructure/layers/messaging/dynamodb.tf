resource "aws_dynamodb_table" "results" {
  count = local.enable_messaging ? 1 : 0

  name         = var.ddb_results_config.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "message_id"

  attribute {
    name = "message_id"
    type = "S"
  }

  attribute {
    name = "run_id"
    type = "S"
  }

  attribute {
    name = "processed_at"
    type = "S"
  }

  global_secondary_index {
    name            = var.ddb_results_config.gsi_name
    hash_key        = "run_id"
    range_key       = "processed_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  ttl {
    enabled        = true
    attribute_name = var.ddb_results_config.ttl_attr
  }

  tags = {
    Name        = var.ddb_results_config.table_name
    Description = "Phase 2 results table Cache Service hits and LLM Service misses both write here"
  }
}
