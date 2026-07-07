# ════════════════════════════════════════════════════════════
#  Lambda (KDS→DynamoDB 적재, 대시보드 조회) + EventBridge + SNS
#  Role은 관리자 사전 생성 ARN(var.lambda_role_arn) 사용
# ════════════════════════════════════════════════════════════

# 실제 코드 zip은 빌드 후 경로 지정. 지금은 placeholder.
# 계정 생성 후 src/ingest, src/query 를 zip 으로 묶어 교체.
data "archive_file" "ingest_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda_src/ingest"
  output_path = "${path.module}/build/ingest.zip"
}

data "archive_file" "query_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda_src/query"
  output_path = "${path.module}/build/query.zip"
}

# ── 적재 Lambda: KDS 이벤트 → DynamoDB ──
resource "aws_lambda_function" "ingest" {
  function_name    = "${var.prefix}-ingest"
  role             = var.lambda_role_arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.ingest_zip.output_path
  source_code_hash = data.archive_file.ingest_zip.output_base64sha256
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.telemetry.name
    }
  }
}

# KDS → 적재 Lambda 트리거
resource "aws_lambda_event_source_mapping" "kds_to_ingest" {
  event_source_arn  = aws_kinesis_stream.telemetry.arn
  function_name     = aws_lambda_function.ingest.arn
  starting_position = "LATEST"
  batch_size        = 200
}

# ── 조회 Lambda: 대시보드 API 백엔드 ──
resource "aws_lambda_function" "query" {
  function_name    = "${var.prefix}-query"
  role             = var.lambda_role_arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.query_zip.output_path
  source_code_hash = data.archive_file.query_zip.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.telemetry.name
    }
  }
}

# ── SNS 크레딧/오류 알림 (SES 대신 SNS — 샌드박스 제약 회피) ──
resource "aws_sns_topic" "alerts" {
  name = "${var.prefix}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── EventBridge: SageMaker 엔드포인트 오토셧다운 스케줄 ──
# (엔드포인트는 SDK로 띄우므로 여기선 "끄는 스케줄"만 준비)
# 매일 한국시간 새벽 3시(UTC 18시)에 셧다운 Lambda 호출하는 룰 예시.
resource "aws_cloudwatch_event_rule" "nightly_shutdown" {
  name                = "${var.prefix}-nightly-shutdown"
  description         = "유휴 시간 SageMaker 엔드포인트 자동 종료"
  schedule_expression = "cron(0 18 * * ? *)"
}
# 대상(셧다운 Lambda)은 엔드포인트 구성 후 연결. 지금은 룰만 생성.
