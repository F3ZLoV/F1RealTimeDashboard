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



