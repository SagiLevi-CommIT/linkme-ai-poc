# ================================================================
# S3 - KB source bucket (normalized text per tenant)
# ================================================================

resource "aws_s3_bucket" "kb_source" {
  bucket = var.kb_source_bucket_name

  tags = {
    Name        = var.kb_source_bucket_name
    Description = "Bedrock KB source normalized text documents per tenant"
  }
}

resource "aws_s3_bucket_versioning" "kb_source" {
  bucket = aws_s3_bucket.kb_source.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "kb_source" {
  bucket = aws_s3_bucket.kb_source.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "kb_source" {
  bucket = aws_s3_bucket.kb_source.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "kb_source" {
  bucket = aws_s3_bucket.kb_source.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "kb_source_ssl_only" {
  statement {
    sid    = "DenyNonSSL"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:*"]
    resources = [aws_s3_bucket.kb_source.arn, "${aws_s3_bucket.kb_source.arn}/*"]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "kb_source" {
  bucket     = aws_s3_bucket.kb_source.id
  policy     = data.aws_iam_policy_document.kb_source_ssl_only.json
  depends_on = [aws_s3_bucket_public_access_block.kb_source]
}

# ================================================================
# S3 - raw uploads bucket (pre-preprocessing)
# ================================================================

resource "aws_s3_bucket" "raw_uploads" {
  bucket = var.raw_uploads_bucket_name

  tags = {
    Name        = var.raw_uploads_bucket_name
    Description = "Raw creator uploads pre-preprocessing PDFs images videos URLs"
  }
}

resource "aws_s3_bucket_versioning" "raw_uploads" {
  bucket = aws_s3_bucket.raw_uploads.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "raw_uploads" {
  bucket = aws_s3_bucket.raw_uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw_uploads" {
  bucket = aws_s3_bucket.raw_uploads.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "raw_uploads" {
  bucket = aws_s3_bucket.raw_uploads.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "raw_uploads_ssl_only" {
  statement {
    sid    = "DenyNonSSL"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:*"]
    resources = [aws_s3_bucket.raw_uploads.arn, "${aws_s3_bucket.raw_uploads.arn}/*"]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "raw_uploads" {
  bucket     = aws_s3_bucket.raw_uploads.id
  policy     = data.aws_iam_policy_document.raw_uploads_ssl_only.json
  depends_on = [aws_s3_bucket_public_access_block.raw_uploads]
}
