# ============================================================
# S3 Vectors - Vector Store for Bedrock Knowledge Base
# ============================================================

resource "aws_s3vectors_vector_bucket" "this" {
  count = local.enable_knowledge_base ? 1 : 0

  vector_bucket_name = local.vector_bucket_name

  tags = {
    Name        = format(local.name_fmt, "s3vec", "kb-vectors")
    Description = "S3 Vectors bucket for Bedrock Knowledge Base vector storage"
  }
}

resource "aws_s3vectors_index" "this" {
  count = local.enable_knowledge_base ? 1 : 0

  index_name         = "${var.project_name}-${var.env}-kb-index"
  vector_bucket_name = aws_s3vectors_vector_bucket.this[0].vector_bucket_name

  data_type       = "float32"
  dimension       = var.vector_dimension
  distance_metric = "cosine"
}
