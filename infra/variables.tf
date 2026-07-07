variable "region" {
  description = "AWS 리전 (제출 견적과 동일하게 us-east-1)"
  type        = string
  default     = "us-east-1"
}

variable "prefix" {
  description = "리소스 이름 접두사 (학교 계정 네임스페이스 규칙)"
  type        = string
  default     = "inhatc-202647019"
}

variable "firehose_role_arn" {
  description = "Firehose 서비스 Role ARN"
  type        = string
  default     = "arn:aws:iam::269578498605:role/FirehoseServiceRole-inhatc-202647019"
}

variable "lambda_role_arn" {
  description = "Lambda 실행 Role ARN"
  type        = string
  default     = "arn:aws:iam::269578498605:role/SafeRole-inhatc-202647019"
}

variable "fargate_task_role_arn" {
  description = "Fargate 태스크 Role ARN"
  type        = string
  default     = "arn:aws:iam::269578498605:role/FargateExecutionRole-inhatc-202647019"
}

variable "alert_email" {
  description = "크레딧/오류 알림 이메일 (SNS 구독)"
  type        = string
  default     = ""
}