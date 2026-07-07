# ════════════════════════════════════════════════════════════
#  수집/저장 핵심 인프라
#  데이터 흐름: Fargate → KDS → (Firehose→S3) + (Lambda→DynamoDB)
# ════════════════════════════════════════════════════════════

# ── Kinesis Data Streams (실시간 수집 버퍼) ──
# 견적 검증: 20명 × 3.7Hz ≈ 75 rec/s → 1샤드(1000 rec/s)로 충분
resource "aws_kinesis_stream" "telemetry" {
  name             = "${var.prefix}-telemetry"
  shard_count      = 1
  retention_period = 24 # 시간 (기본값, 길게 잡으면 비용↑)

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }
}

# ── DynamoDB (실시간 텔레메트리 시계열) ──
# 키 모델: PK="{session}#{driver}", SK="{type}#{date}"
resource "aws_dynamodb_table" "telemetry" {
  name         = "${var.prefix}-telemetry"
  billing_mode = "PAY_PER_REQUEST" # 온디맨드
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  # 오래된 실시간 데이터 자동 정리 (TTL) — 비용 절감
  ttl {
    attribute_name = "expire_at"
    enabled        = true
  }
}

# ── S3 데이터 레이크 (아카이브 + ML 학습 데이터) ──
resource "aws_s3_bucket" "lake" {
  bucket = "${var.prefix}-datalake-${data.aws_caller_identity.me.account_id}"
}

resource "aws_s3_bucket_public_access_block" "lake" {
  bucket                  = aws_s3_bucket.lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── S3 대시보드 호스팅 버킷 (정적 웹) ──
resource "aws_s3_bucket" "dashboard" {
  bucket = "${var.prefix}-dashboard-${data.aws_caller_identity.me.account_id}"
}

resource "aws_s3_bucket_public_access_block" "dashboard" {
  bucket                  = aws_s3_bucket.dashboard.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Data Firehose: KDS → Parquet → S3 데이터레이크 ──
# 견적: Parquet 변환 활성. Role은 관리자가 사전 생성한 ARN 사용.
resource "aws_kinesis_firehose_delivery_stream" "to_lake" {
  name        = "${var.prefix}-to-lake"
  destination = "extended_s3"

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.telemetry.arn
    role_arn           = var.firehose_role_arn
  }

  extended_s3_configuration {
    role_arn   = var.firehose_role_arn
    bucket_arn = aws_s3_bucket.lake.arn
    prefix     = "telemetry/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "errors/"

    buffering_size     = 64 # MB
    buffering_interval = 300 # 초

    # Parquet 변환은 Glue 테이블 스키마가 필요.
    # 계정 생성 후 Glue 테이블 만들고 아래 블록 주석 해제:
    #
    # data_format_conversion_configuration {
    #   output_format_configuration {
    #     serializer { parquet_ser_de {} }
    #   }
    #   schema_configuration {
    #     database_name = aws_glue_catalog_table.telemetry.database_name
    #     table_name    = aws_glue_catalog_table.telemetry.name
    #     role_arn      = var.firehose_role_arn
    #   }
    # }
  }
}

data "aws_caller_identity" "me" {}
