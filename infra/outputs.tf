output "kinesis_stream_name" {
  description = "Fargate 컨슈머가 PutRecords 할 스트림 이름"
  value       = aws_kinesis_stream.telemetry.name
}

output "kinesis_stream_arn" {
  value = aws_kinesis_stream.telemetry.arn
}

output "dynamodb_table" {
  description = "조회/적재 Lambda가 쓸 테이블 이름"
  value       = aws_dynamodb_table.telemetry.name
}

output "datalake_bucket" {
  description = "Firehose가 Parquet 적재 + SageMaker 학습 데이터 소스"
  value       = aws_s3_bucket.lake.bucket
}

output "dashboard_bucket" {
  description = "대시보드 정적 파일 업로드 대상"
  value       = aws_s3_bucket.dashboard.bucket
}

output "api_endpoint" {
  description = "대시보드 fetch가 호출할 API URL (GET /telemetry)"
  value       = "${aws_apigatewayv2_api.dashboard_api.api_endpoint}/telemetry"
}

output "dashboard_url" {
  description = "배포된 대시보드 주소"
  value       = "https://${aws_cloudfront_distribution.dashboard.domain_name}"
}

