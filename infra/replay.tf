# ════════════════════════════════════════════════════════════
#  리플레이 백엔드 — 청크 빌더 + 세션 목록 Lambda, API 라우트
#  프론트(Next.js 정적 빌드)는 S3+CloudFront, 데이터는 여기로.
# ════════════════════════════════════════════════════════════

data "archive_file" "replay_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda_src/replay"
  output_path = "${path.module}/build/replay.zip"
}

data "archive_file" "sessions_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda_src/sessions"
  output_path = "${path.module}/build/sessions.zip"
}

# ── 리플레이 청크 빌더 ──
# OpenF1 수집 + 병합이 무거워 메모리를 넉넉히 (CPU도 비례해서 올라감)
resource "aws_lambda_function" "replay" {
  function_name    = "${var.prefix}-replay"
  role             = var.lambda_role_arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.replay_zip.output_path
  source_code_hash = data.archive_file.replay_zip.output_base64sha256
  timeout          = 60
  memory_size      = 1024

  environment {
    variables = {
      CACHE_BUCKET = aws_s3_bucket.lake.bucket
      CACHE_PREFIX = "replay-cache"
    }
  }
}

# ── 세션/그랑프리 목록 ──
resource "aws_lambda_function" "sessions" {
  function_name    = "${var.prefix}-sessions"
  role             = var.lambda_role_arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.sessions_zip.output_path
  source_code_hash = data.archive_file.sessions_zip.output_base64sha256
  timeout          = 25
  memory_size      = 256
}

# ── API 라우트 ──
resource "aws_apigatewayv2_integration" "replay" {
  api_id                 = aws_apigatewayv2_api.dashboard_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.replay.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000 # HTTP API 상한
}

resource "aws_apigatewayv2_route" "get_replay" {
  api_id    = aws_apigatewayv2_api.dashboard_api.id
  route_key = "GET /replay"
  target    = "integrations/${aws_apigatewayv2_integration.replay.id}"
}

resource "aws_lambda_permission" "api_invoke_replay" {
  statement_id  = "AllowAPIGwInvokeReplay"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.replay.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.dashboard_api.execution_arn}/*/*"
}

resource "aws_apigatewayv2_integration" "sessions" {
  api_id                 = aws_apigatewayv2_api.dashboard_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.sessions.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "get_sessions" {
  api_id    = aws_apigatewayv2_api.dashboard_api.id
  route_key = "GET /sessions"
  target    = "integrations/${aws_apigatewayv2_integration.sessions.id}"
}

resource "aws_lambda_permission" "api_invoke_sessions" {
  statement_id  = "AllowAPIGwInvokeSessions"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sessions.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.dashboard_api.execution_arn}/*/*"
}

output "replay_api_base" {
  description = "프론트가 호출할 API 베이스 (NEXT_PUBLIC_API_BASE)"
  value       = aws_apigatewayv2_api.dashboard_api.api_endpoint
}
