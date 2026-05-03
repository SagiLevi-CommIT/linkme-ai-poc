resource "aws_s3_bucket" "input_messages" {
  count = local.enable_messaging ? 1 : 0

  bucket = "${var.s3_input_messages_bucket}-${var.account_id}"

  tags = {
    Name        = "${var.s3_input_messages_bucket}-${var.account_id}"
    Description = "Simulator input JSONL batches under messages prefix"
  }
}

resource "aws_s3_bucket_ownership_controls" "input_messages" {
  count = local.enable_messaging ? 1 : 0

  bucket = aws_s3_bucket.input_messages[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "input_messages" {
  count = local.enable_messaging ? 1 : 0

  bucket = aws_s3_bucket.input_messages[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "input_messages" {
  count = local.enable_messaging ? 1 : 0

  bucket = aws_s3_bucket.input_messages[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "input_messages" {
  count = local.enable_messaging ? 1 : 0

  bucket = aws_s3_bucket.input_messages[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "input_messages" {
  count = local.enable_messaging ? 1 : 0

  bucket = aws_s3_bucket.input_messages[0].id

  rule {
    id     = "expire-input-batches"
    status = "Enabled"

    filter {
      prefix = "messages/"
    }

    expiration {
      days = 7
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}

data "aws_iam_policy_document" "input_messages_ssl_only" {
  count = local.enable_messaging ? 1 : 0

  statement {
    sid       = "DenyInsecureConnections"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.input_messages[0].arn, "${aws_s3_bucket.input_messages[0].arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "input_messages" {
  count = local.enable_messaging ? 1 : 0

  bucket = aws_s3_bucket.input_messages[0].id
  policy = data.aws_iam_policy_document.input_messages_ssl_only[0].json
}
