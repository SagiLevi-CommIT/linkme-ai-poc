resource "aws_bedrockagent_knowledge_base" "this" {
  count = local.enable_knowledge_base ? 1 : 0

  name     = format(local.name_short, "kb")
  role_arn = aws_iam_role.kb[0].arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = var.embedding_model_arn
      embedding_model_configuration {
        bedrock_embedding_model_configuration {
          dimensions          = var.vector_dimension
          embedding_data_type = "FLOAT32"
        }
      }
    }
  }

  storage_configuration {
    type = "S3_VECTORS"
    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.this[0].index_arn
    }
  }

  tags = {
    Name        = format(local.name_short, "kb")
    Description = "LinkMe POC multi-tenant KB backed by Titan V2 1024-dim and S3 Vectors"
  }
}

resource "aws_bedrockagent_data_source" "s3" {
  count = local.enable_knowledge_base ? 1 : 0

  knowledge_base_id = aws_bedrockagent_knowledge_base.this[0].id
  name              = "${var.project_name}-${var.env}-kb-s3-source"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn = aws_s3_bucket.kb_source.arn
    }
  }

  # Retain vector data on deletion so KB cleanup does not fail if the vector store is rebuilt
  data_deletion_policy = "RETAIN"
}
