#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  destroy.sh — 전체 인프라 내리기 (크레딧 절약)
#
#  순서 중요: S3 비우기 → CLI 생성 리소스 삭제 → terraform destroy
#            → KDS 직접 삭제(terraform 관리 밖) → 최종 확인
#
#  학교 계정은 SNS:DeleteTopic, cloudfront:DeleteDistribution 이 막혀
#  이 둘은 남을 수 있음(트래픽 0이면 과금 0). 관리자에게 정리 요청 가능.
#
#  사용법:  cd ~/F1RealTimeDashboard && bash scripts/destroy.sh
# ══════════════════════════════════════════════════════════════
set -uo pipefail
ACCT=269578498605
PREFIX=inhatc-202647019
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH=/tmp:$PATH
export TF_PLUGIN_CACHE_DIR=/tmp/tfcache
mkdir -p /tmp/tfcache

echo "현재 계정: $(aws sts get-caller-identity --query Arn --output text)"
read -p "정말 전체 삭제? (yes 입력): " CONFIRM
[ "$CONFIRM" = "yes" ] || { echo "취소됨"; exit 0; }

# 1) S3 비우기 (버킷은 비어야 삭제 가능)
echo "── S3 비우는 중 ──"
aws s3 rm s3://${PREFIX}-datalake-${ACCT}  --recursive 2>/dev/null
aws s3 rm s3://${PREFIX}-dashboard-${ACCT} --recursive 2>/dev/null

# 2) Firehose (CLI 생성 → CLI 삭제)
echo "── Firehose 삭제 ──"
aws firehose delete-delivery-stream --delivery-stream-name ${PREFIX}-to-lake 2>/dev/null \
  && echo "요청됨" || echo "없음(스킵)"

# 3) API 라우트/통합 (CLI 생성분)
echo "── API 라우트/통합 정리 ──"
API_ID=$(aws apigatewayv2 get-apis --query "Items[?Name=='${PREFIX}-api'].ApiId" --output text 2>/dev/null)
if [ -n "$API_ID" ] && [ "$API_ID" != "None" ]; then
  RID=$(aws apigatewayv2 get-routes --api-id "$API_ID" --query "Items[?RouteKey=='GET /telemetry'].RouteId" --output text 2>/dev/null)
  [ -n "$RID" ] && aws apigatewayv2 delete-route --api-id "$API_ID" --route-id "$RID" 2>/dev/null
  IID=$(aws apigatewayv2 get-integrations --api-id "$API_ID" --query "Items[0].IntegrationId" --output text 2>/dev/null)
  [ -n "$IID" ] && [ "$IID" != "None" ] && aws apigatewayv2 delete-integration --api-id "$API_ID" --integration-id "$IID" 2>/dev/null
  echo "라우트/통합 정리됨"
fi

# 4) terraform destroy (나머지)
echo "── terraform destroy ──"
cd "$ROOT/infra"
terraform destroy -auto-approve

# 5) KDS 직접 삭제 (terraform state에서 rm 했을 수 있어 별도)
echo "── KDS 삭제 (terraform 관리 밖) ──"
aws kinesis delete-stream --stream-name ${PREFIX}-telemetry --enforce-consumer-deletion 2>/dev/null \
  && echo "요청됨" || echo "없음(이미 삭제)"

# 6) 최종 확인 (과금 큰 것들이 다 비어야 정상)
echo ""
echo "════════ 최종 확인 (비어야 정상) ════════"
echo -n "KDS:      "; aws kinesis list-streams --query 'StreamNames' --output text
echo -n "Firehose: "; aws firehose list-delivery-streams --query 'DeliveryStreamNames' --output text
echo -n "DynamoDB: "; aws dynamodb list-tables --query "TableNames[?contains(@,'${PREFIX}')]" --output text
echo -n "Lambda:   "; aws lambda list-functions --query "Functions[?contains(FunctionName,'${PREFIX}')].FunctionName" --output text
echo ""
echo "※ SNS/CloudFront는 삭제 권한이 없어 남을 수 있음 (트래픽 0이면 과금 0)."
echo "  완전 삭제하려면 관리자에게 SNS:DeleteTopic, cloudfront:DeleteDistribution 요청."
