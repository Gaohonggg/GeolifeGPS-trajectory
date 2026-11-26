# Function API, alias live và challenger.
# publish = true: mỗi lần cấu hình làm việc ($LATEST) đổi image hoặc MODEL_URI, Lambda đóng một version mới, bất biến.
# Không alias nào trỏ vào $LATEST; hai alias trỏ vào version ghi trong models.auto.tfvars.json.

resource "aws_iam_role" "api" {
  name = "${local.name}-api"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Đọc điểm và model. Không quyền ghi vào bucket.
# s3:ListBucket trên hai prefix: thiếu quyền này, S3 trả 403 cho object không tồn tại thay vì 404,
# nên không phân biệt được user không tồn tại với lỗi quyền; MLflow cũng liệt kê thư mục model khi tải.
resource "aws_iam_role_policy" "api" {
  name = "read-artifacts"
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "s3:GetObject"
        Resource = [
          "${local.foundation.artifacts_bucket_arn}/data/serving/*",
          "${local.foundation.artifacts_bucket_arn}/${local.model_prefix}/*",
        ]
      },
      {
        Effect    = "Allow"
        Action    = "s3:ListBucket"
        Resource  = local.foundation.artifacts_bucket_arn
        Condition = { StringLike = { "s3:prefix" = ["data/serving/*", "${local.model_prefix}/*"] } }
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.api.arn}:*"
      },
    ]
  })
}

# Tạo trước function để đặt retention; nếu để Lambda tự tạo thì log giữ vô hạn.
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name}-api"
  retention_in_days = var.api_log_retention_days
}

resource "aws_lambda_function" "api" {
  function_name = "${local.name}-api"
  role          = aws_iam_role.api.arn
  package_type  = "Image"
  image_uri     = local.image
  architectures = ["arm64"]
  memory_size   = var.api_memory
  timeout       = var.api_timeout
  publish       = true

  reserved_concurrent_executions = var.paused ? 0 : var.api_reserved_concurrency

  image_config {
    entry_point = ["python", "-m", "awslambdaric"]
    command     = ["geolife_api.lambda_handlers.api"]
  }

  environment {
    variables = {
      MODEL_URI  = "s3://${local.bucket}/${local.model_prefix}/v=${var.latest_model_version}/model"
      POINTS_URI = local.points_uri
    }
  }

  # Log JSON: dòng REPORT (initDurationMs, maxMemoryUsedMB) truy vấn được bằng Logs Insights.
  logging_config {
    log_format            = "JSON"
    log_group             = aws_cloudwatch_log_group.api.name
    application_log_level = "INFO"
    system_log_level      = "INFO"
  }

  depends_on = [aws_iam_role_policy.api]
}

locals {
  live_version = var.live.lambda_version != null ? tostring(var.live.lambda_version) : aws_lambda_function.api.version
  # Không có @challenger: alias challenger trùng version của live.
  challenger_version = var.challenger != null ? tostring(var.challenger.lambda_version) : local.live_version
  canary             = local.challenger_version != local.live_version && var.canary_weight > 0
}

# Alias live (API Gateway gọi): khi đang canary, Lambda chia ngẫu nhiên từng lần gọi, canary_weight % sang version của
# challenger. Metric của Lambda theo alias có dimension ExecutedVersion để tách hai version.
resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.api.function_name
  function_version = local.live_version

  dynamic "routing_config" {
    for_each = local.canary ? [1] : []
    content {
      additional_version_weights = { (local.challenger_version) = var.canary_weight / 100 }
    }
  }
}

# Alias challenger: gọi thẳng version mới, không qua chia traffic của live.
resource "aws_lambda_alias" "challenger" {
  name             = "challenger"
  function_name    = aws_lambda_function.api.function_name
  function_version = local.challenger_version
}

# Function URL của alias challenger. AWS_IAM: request phải ký SigV4 bằng credential có quyền
# lambda:InvokeFunctionUrl trên function (user dev trong cùng tài khoản), nên URL không mở công khai.
resource "aws_lambda_function_url" "challenger" {
  function_name      = aws_lambda_function.api.function_name
  qualifier          = aws_lambda_alias.challenger.name
  authorization_type = "AWS_IAM"
}
