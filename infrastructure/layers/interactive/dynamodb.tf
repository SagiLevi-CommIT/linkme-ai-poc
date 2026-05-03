resource "aws_dynamodb_table" "this" {
  for_each = var.ddb_tables

  name         = each.value.name
  billing_mode = each.value.billing_mode
  hash_key     = each.value.hash_key

  attribute {
    name = each.value.hash_key
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Name        = each.value.name
    Description = "LinkMe POC interactive ${each.key} table"
  }
}
