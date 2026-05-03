resource "terraform_data" "api_package_build" {
  count = var.enable_api_lambda ? 1 : 0

  triggers_replace = {
    src_sha = sha1(join("", [for f in fileset(var.api_lambda_config.package_path, "**") : filesha1("${var.api_lambda_config.package_path}/${f}")]))
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      STAGE="${path.module}/.build/api_pkg"
      rm -rf "$STAGE" && mkdir -p "$STAGE"
      cp -r "${var.api_lambda_config.package_path}"/* "$STAGE"/
      python3 -m pip install \
        --target "$STAGE" \
        --platform manylinux2014_aarch64 \
        --implementation cp \
        --python-version 3.12 \
        --only-binary=:all: \
        --upgrade \
        -r "${var.api_lambda_config.package_path}/../requirements.txt"
    EOT
  }
}

data "archive_file" "api_package" {
  count      = var.enable_api_lambda ? 1 : 0
  depends_on = [terraform_data.api_package_build]

  type        = "zip"
  source_dir  = "${path.module}/.build/api_pkg"
  output_path = "${path.module}/.build/api_lambda.zip"
}

resource "aws_cloudwatch_log_group" "api" {
  count = var.enable_api_lambda ? 1 : 0

  name              = "/aws/lambda/${var.api_lambda_config.function_name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.cloudwatch_kms_key_arn

  tags = {
    Name        = format(local.name_fmt, "log", "api-lambda")
    Description = "API Lambda logs"
  }
}

resource "aws_iam_role" "api" {
  count = var.enable_api_lambda ? 1 : 0

  name               = format(local.name_fmt, "role", "api-lambda")
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  tags = {
    Name        = format(local.name_fmt, "role", "api-lambda")
    Description = "Execution role for linkme-poc-api Lambda"
  }
}

resource "aws_iam_role_policy_attachment" "api_basic_logs" {
  count = var.enable_api_lambda ? 1 : 0

  role       = aws_iam_role.api[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "api_inline" {
  count = var.enable_api_lambda ? 1 : 0

  statement {
    sid       = "DDBReadWrite"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem"]
    resources = concat([for t in aws_dynamodb_table.this : t.arn], [var.results_table_arn])
  }

  statement {
    sid       = "S3RawUploadsReadWrite"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${var.raw_uploads_bucket_arn}/*"]
  }

  statement {
    sid       = "S3RawUploadsList"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [var.raw_uploads_bucket_arn]
  }

  statement {
    sid       = "SQSEnqueueIncoming"
    effect    = "Allow"
    actions   = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
    resources = [var.incoming_queue_arn]
  }
}

resource "aws_iam_role_policy" "api_inline" {
  count = var.enable_api_lambda ? 1 : 0

  name   = "inline"
  role   = aws_iam_role.api[0].id
  policy = data.aws_iam_policy_document.api_inline[0].json
}

resource "aws_lambda_function" "api" {
  count = var.enable_api_lambda ? 1 : 0

  function_name    = var.api_lambda_config.function_name
  role             = aws_iam_role.api[0].arn
  runtime          = var.api_lambda_config.runtime
  handler          = var.api_lambda_config.handler
  memory_size      = var.api_lambda_config.memory_mb
  timeout          = var.api_lambda_config.timeout_s
  filename         = data.archive_file.api_package[0].output_path
  source_code_hash = data.archive_file.api_package[0].output_base64sha256
  architectures    = ["arm64"]

  environment {
    variables = {
      DDB_PROFILES_TABLE       = aws_dynamodb_table.this["profiles"].name
      DDB_CACHE_TABLE          = aws_dynamodb_table.this["cache"].name
      DDB_MESSAGES_TABLE       = aws_dynamodb_table.this["messages"].name
      DDB_SEMANTIC_CACHE_TABLE = aws_dynamodb_table.this["semantic_cache"].name
      DDB_RESULTS_TABLE        = var.results_table_name
      INCOMING_QUEUE_URL       = var.incoming_queue_url
      KB_ID                    = var.knowledge_base_id
      RAW_UPLOADS_BUCKET       = var.raw_uploads_bucket_name
      KB_SOURCE_BUCKET         = var.kb_source_bucket_name
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = {
    Name        = var.api_lambda_config.function_name
    Description = "LinkMe POC API Lambda submit question poll results profile and document CRUD"
  }

  depends_on = [aws_cloudwatch_log_group.api]
}

resource "aws_lambda_function_url" "api" {
  count = var.enable_api_lambda ? 1 : 0

  function_name      = aws_lambda_function.api[0].function_name
  authorization_type = "NONE" # POC - flip to AWS_IAM for production

  cors {
    allow_origins = ["*"]
    allow_methods = ["*"]
    allow_headers = ["*"]
    max_age       = 3600
  }
}
