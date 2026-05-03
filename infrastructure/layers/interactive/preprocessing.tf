resource "terraform_data" "preprocessor_package_build" {
  count = var.enable_preprocessor ? 1 : 0

  triggers_replace = {
    src_sha = sha1(join("", [for f in fileset(var.preprocessor_lambda_config.package_path, "**") : filesha1("${var.preprocessor_lambda_config.package_path}/${f}")]))
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      STAGE="${path.module}/.build/preprocessor_pkg"
      rm -rf "$STAGE" && mkdir -p "$STAGE"
      cp -r "${var.preprocessor_lambda_config.package_path}"/* "$STAGE"/
      python3 -m pip install \
        --target "$STAGE" \
        --platform manylinux2014_aarch64 \
        --implementation cp \
        --python-version 3.12 \
        --only-binary=:all: \
        --upgrade \
        -r "${var.preprocessor_lambda_config.package_path}/../requirements.txt"
    EOT
  }
}

data "archive_file" "preprocessor_package" {
  count      = var.enable_preprocessor ? 1 : 0
  depends_on = [terraform_data.preprocessor_package_build]

  type        = "zip"
  source_dir  = "${path.module}/.build/preprocessor_pkg"
  output_path = "${path.module}/.build/preprocessor_lambda.zip"
}

resource "aws_cloudwatch_log_group" "preprocessor" {
  count = var.enable_preprocessor ? 1 : 0

  name              = "/aws/lambda/${var.preprocessor_lambda_config.function_name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.cloudwatch_kms_key_arn

  tags = {
    Name        = format(local.name_fmt, "log", "preprocessing-lambda")
    Description = "Preprocessing Lambda logs"
  }
}

resource "aws_iam_role" "preprocessor" {
  count = var.enable_preprocessor ? 1 : 0

  name               = format(local.name_fmt, "role", "preprocessing-lambda")
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  tags = {
    Name        = format(local.name_fmt, "role", "preprocessing-lambda")
    Description = "Execution role for linkme-poc-preprocessing Lambda"
  }
}

resource "aws_iam_role_policy_attachment" "preprocessor_basic_logs" {
  count = var.enable_preprocessor ? 1 : 0

  role       = aws_iam_role.preprocessor[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "preprocessor_inline" {
  count = var.enable_preprocessor ? 1 : 0

  statement {
    sid       = "S3RawUploadsRead"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:GetObjectTagging"]
    resources = ["${var.raw_uploads_bucket_arn}/*"]
  }

  statement {
    sid       = "S3KbSourceWrite"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:PutObjectTagging", "s3:GetObject"]
    resources = ["arn:aws:s3:::${var.kb_source_bucket_name}/*"]
  }

  statement {
    sid     = "BedrockInvokeNovaLite"
    effect  = "Allow"
    actions = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:${var.region}::foundation-model/amazon.nova-lite-v1:0",
      "arn:aws:bedrock:${var.region}:${var.account_id}:inference-profile/us.amazon.nova-lite-v1:0",
    ]
  }

  statement {
    sid       = "BedrockKBIngestion"
    effect    = "Allow"
    actions   = ["bedrock:StartIngestionJob", "bedrock:GetIngestionJob", "bedrock:ListIngestionJobs"]
    resources = ["arn:aws:bedrock:${var.region}:${var.account_id}:knowledge-base/${var.knowledge_base_id}"]
  }
}

resource "aws_iam_role_policy" "preprocessor_inline" {
  count = var.enable_preprocessor ? 1 : 0

  name   = "inline"
  role   = aws_iam_role.preprocessor[0].id
  policy = data.aws_iam_policy_document.preprocessor_inline[0].json
}

resource "aws_lambda_function" "preprocessor" {
  count = var.enable_preprocessor ? 1 : 0

  function_name    = var.preprocessor_lambda_config.function_name
  role             = aws_iam_role.preprocessor[0].arn
  runtime          = var.preprocessor_lambda_config.runtime
  handler          = var.preprocessor_lambda_config.handler
  memory_size      = var.preprocessor_lambda_config.memory_mb
  timeout          = var.preprocessor_lambda_config.timeout_s
  filename         = data.archive_file.preprocessor_package[0].output_path
  source_code_hash = data.archive_file.preprocessor_package[0].output_base64sha256
  architectures    = ["arm64"]

  environment {
    variables = {
      KB_ID              = var.knowledge_base_id
      KB_SOURCE_BUCKET   = var.kb_source_bucket_name
      RAW_UPLOADS_BUCKET = var.raw_uploads_bucket_name
      NOVA_MODEL_ID      = "us.amazon.nova-lite-v1:0"
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = {
    Name        = var.preprocessor_lambda_config.function_name
    Description = "S3-event-driven preprocessor PDFs URLs via parser multimodal via Nova Lite then KB ingestion"
  }

  depends_on = [aws_cloudwatch_log_group.preprocessor]
}

resource "aws_lambda_permission" "preprocessor_s3" {
  count = var.enable_preprocessor ? 1 : 0

  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.preprocessor[0].function_name
  principal     = "s3.amazonaws.com"
  source_arn    = var.raw_uploads_bucket_arn
}

resource "aws_s3_bucket_notification" "raw_uploads" {
  count = var.enable_preprocessor ? 1 : 0

  bucket = var.raw_uploads_bucket_name

  lambda_function {
    lambda_function_arn = aws_lambda_function.preprocessor[0].arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_lambda_permission.preprocessor_s3]
}
