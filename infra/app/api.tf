# HTTP API: URL HTTPS công khai, chuyển mọi request tới alias live (payload v2).
# Một route $default: mọi method và path tới FastAPI, nên path lạ vẫn trả 404 theo contract.
# HTTP API không lọc theo IP; giới hạn thiệt hại bằng throttling ở đây và reserved concurrency của function.

resource "aws_apigatewayv2_api" "api" {
  name          = "${local.name}-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "live" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.live.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.live.id}"
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/${local.name}-api"
  retention_in_days = 14
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.throttle_rate
    throttling_burst_limit = var.throttle_burst
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId         = "$context.requestId"
      time              = "$context.requestTime"
      method            = "$context.httpMethod"
      path              = "$context.path"
      status            = "$context.status"
      latencyMs         = "$context.responseLatency"
      integrationMs     = "$context.integrationLatency"
      integrationStatus = "$context.integrationStatus"
      integrationError  = "$context.integrationErrorMessage"
      lambdaRequestId   = "$context.integration.requestId"
      sourceIp          = "$context.identity.sourceIp"
      responseLength    = "$context.responseLength"
    })
  }
}

# Quyền theo resource: chỉ API này được gọi alias live.
resource "aws_lambda_permission" "apigw_live" {
  statement_id  = "apigw-invoke-live"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  qualifier     = aws_lambda_alias.live.name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*"
}
