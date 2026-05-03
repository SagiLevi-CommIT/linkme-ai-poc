resource "aws_s3_bucket" "ui" {
  count = var.enable_ui_bucket ? 1 : 0

  bucket = var.ui_bucket_name

  tags = {
    Name        = var.ui_bucket_name
    Description = "LinkMe POC UI static site Setup Assistant Live Test"
  }
}

resource "aws_s3_bucket_ownership_controls" "ui" {
  count = var.enable_ui_bucket ? 1 : 0

  bucket = aws_s3_bucket.ui[0].id

  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_public_access_block" "ui" {
  count = var.enable_ui_bucket ? 1 : 0

  bucket = aws_s3_bucket.ui[0].id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_website_configuration" "ui" {
  count = var.enable_ui_bucket ? 1 : 0

  bucket = aws_s3_bucket.ui[0].id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

data "aws_iam_policy_document" "ui_public_read" {
  count = var.enable_ui_bucket ? 1 : 0

  statement {
    sid       = "PublicReadForWebsite"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.ui[0].arn}/*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
  }
}

resource "aws_s3_bucket_policy" "ui" {
  count = var.enable_ui_bucket ? 1 : 0

  bucket     = aws_s3_bucket.ui[0].id
  policy     = data.aws_iam_policy_document.ui_public_read[0].json
  depends_on = [aws_s3_bucket_public_access_block.ui]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ui" {
  count = var.enable_ui_bucket ? 1 : 0

  bucket = aws_s3_bucket.ui[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "ui" {
  count = var.enable_ui_bucket ? 1 : 0

  bucket = aws_s3_bucket.ui[0].id

  versioning_configuration {
    status = "Enabled"
  }
}
