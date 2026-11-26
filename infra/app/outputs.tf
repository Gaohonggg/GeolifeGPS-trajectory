# invoke_url của stage $default kết thúc bằng "/"; bỏ đi để ghép được "$(url)/v1/..."
output "url" { value = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/") }
output "image" { value = local.image }
output "function_name" { value = aws_lambda_function.api.function_name }
output "api_reserved_concurrency" { value = var.api_reserved_concurrency }

# Version vừa đóng từ $LATEST; make aws-promote đọc để ghi vào models.auto.tfvars.json.
output "published_version" { value = aws_lambda_function.api.version }

output "live" {
  value = {
    lambda_version = aws_lambda_alias.live.function_version
    model_version  = var.live.model_version
    canary_weight  = local.canary ? var.canary_weight : 0
  }
}

output "challenger" {
  value = {
    lambda_version = aws_lambda_alias.challenger.function_version
    model_version  = var.challenger != null ? var.challenger.model_version : var.live.model_version
  }
}

# make aws-call-challenger ký request tới URL này bằng SigV4; kết thúc bằng "/" như invoke_url.
output "challenger_url" { value = trimsuffix(aws_lambda_function_url.challenger.function_url, "/") }
