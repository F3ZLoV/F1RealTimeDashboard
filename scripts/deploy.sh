#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  deploy.sh — F1 대시보드 인프라 전체 배포 (CloudShell용)
#
#  학교 계정(SafePowerUser) 제약 대응:
#   - Terraform이 태그/TTL/event source mapping 에서 막히므로
#     핵심은 Terraform, 막히는 부분은 CLI로 보완한다.
#   - 리소스는 전부 inhatc-202647019- prefix.
#
#  사전조건:
#   - CloudShell (자격증명 자동), 계정 = 269578498605 / inhatc-202647019
#   - terraform 설치됨 (없으면 scripts/00_setup_cloudshell.sh)
#   - infra/variables.tf 에 Role ARN 채워져 있음
#
#  사용법:  cd ~/F1RealTimeDashboard && bash scripts/deploy.sh
# ══════════════════════════════════════════════════════════════
set -uo pipefail   # set -e 는 일부러 뺌 (권한 막힌 단계 스킵 위해)

# ── 설정 ──────────────────────────────────────────────
ACCT=269578498605
REGION=us-east-1
PREFIX=inhatc-202647019
STREAM=${PREFIX}-telemetry
DDB=${PREFIX}-telemetry
DASH_BUCKET=${PREFIX}-dashboard-${ACCT}
LAKE_BUCKET=${PREFIX}-datalake-${ACCT}
FH_ROLE=arn:aws:iam::${ACCT}:role/FirehoseServiceRole-${PREFIX}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# terraform 경로 (CloudShell 재시작 시 /tmp에 두는 관례)
export PATH=/tmp:$PATH
export TF_PLUGIN_CACHE_DIR=/tmp/tfcache
mkdir -p /tmp/tfcache

echo "════════════════════════════════════════"
echo " F1 Dashboard 배포 시작"
echo "════════════════════════════════════════"

# ── 0) 계정 확인 (안전장치) ──────────────────────────
ARN=$(aws sts get-caller-identity --query Arn --output text)
echo "현재 계정: $ARN"
case "$ARN" in
  *inhatc-202647019*) echo "✅ 계정 확인 OK" ;;
  *) echo "❌ 계정이 inhatc-202647019 가 아님! 중단."; echo "   rm -f ~/.aws/credentials ~/.aws/config 후 재시도"; exit 1 ;;
esac

# ── 1) Terraform 배포 (핵심 인프라) ──────────────────
echo ""
echo "── 1) terraform apply ──"
cd "$ROOT/infra"
terraform init -input=false
terraform apply -auto-approve
echo "terraform apply 완료 (일부 리소스는 권한상 CLI 보완 필요할 수 있음)"

# terraform output 값 확보 (실패해도 진행)
API_ID=$(aws apigatewayv2 get-apis --query "Items[?Name=='${PREFIX}-api'].ApiId" --output text 2>/dev/null)
echo "API_ID = ${API_ID:-없음}"

# ── 2) API Gateway 라우트/통합/권한 (CLI 보완) ───────
# terraform이 event source mapping 등에서 실패하면 라우트도 안 붙는 경우가 있어 멱등 생성
echo ""
echo "── 2) API 라우트/통합/권한 (CLI 보완) ──"
if [ -n "$API_ID" ] && [ "$API_ID" != "None" ]; then
  LAMBDA_ARN=arn:aws:lambda:${REGION}:${ACCT}:function:${PREFIX}-query
  # 기존 라우트 있으면 스킵
  HAS_ROUTE=$(aws apigatewayv2 get-routes --api-id "$API_ID" --query "Items[?RouteKey=='GET /telemetry'].RouteId" --output text 2>/dev/null)
  if [ -z "$HAS_ROUTE" ]; then
    INTEG_ID=$(aws apigatewayv2 create-integration --api-id "$API_ID" \
      --integration-type AWS_PROXY --integration-uri "$LAMBDA_ARN" \
      --payload-format-version 2.0 --query IntegrationId --output text)
    aws apigatewayv2 create-route --api-id "$API_ID" \
      --route-key "GET /telemetry" --target "integrations/$INTEG_ID" >/dev/null
    aws lambda add-permission --function-name ${PREFIX}-query \
      --statement-id apigw-invoke --action lambda:InvokeFunction \
      --principal apigateway.amazonaws.com \
      --source-arn "arn:aws:execute-api:${REGION}:${ACCT}:${API_ID}/*/*" >/dev/null 2>&1
    echo "✅ 라우트/통합/권한 생성"
  else
    echo "✅ 라우트 이미 존재 (스킵)"
  fi
  # CORS (브라우저 접근용)
  aws apigatewayv2 update-api --api-id "$API_ID" \
    --cors-configuration AllowOrigins="*",AllowMethods="*",AllowHeaders="*",MaxAge=300 >/dev/null
  echo "✅ CORS 설정"
else
  echo "⚠️ API_ID 없음 — API Gateway가 안 만들어짐. terraform 로그 확인 필요"
fi

# ── 3) Firehose (KDS→S3), terraform이 막히면 CLI ─────
echo ""
echo "── 3) Firehose 확인/생성 ──"
if aws firehose describe-delivery-stream --delivery-stream-name ${PREFIX}-to-lake >/dev/null 2>&1; then
  echo "✅ Firehose 이미 존재"
else
  aws firehose create-delivery-stream \
    --delivery-stream-name ${PREFIX}-to-lake \
    --delivery-stream-type KinesisStreamAsSource \
    --kinesis-stream-source-configuration \
      "KinesisStreamARN=arn:aws:kinesis:${REGION}:${ACCT}:stream/${STREAM},RoleARN=${FH_ROLE}" \
    --extended-s3-destination-configuration \
      "RoleARN=${FH_ROLE},BucketARN=arn:aws:s3:::${LAKE_BUCKET},Prefix=telemetry/,BufferingHints={SizeInMBs=64,IntervalInSeconds=60}" \
    >/dev/null 2>&1 && echo "✅ Firehose 생성" || echo "⚠️ Firehose 생성 실패 (Role 신뢰관계 확인)"
fi

# ── 4) 대시보드 S3 업로드 ────────────────────────────
echo ""
echo "── 4) 대시보드 배포 ──"
if [ -n "$API_ID" ] && [ "$API_ID" != "None" ]; then
  API_ENDPOINT="https://${API_ID}.execute-api.${REGION}.amazonaws.com/telemetry"
  cd "$ROOT"
  # api_loader.js 의 API_ENDPOINT 치환 (자리표시자 또는 기존 URL 모두 대응)
  sed -i "s|const API_ENDPOINT = \"[^\"]*\";|const API_ENDPOINT = \"${API_ENDPOINT}\";|" api_loader.js
  # 대시보드가 api_loader.js 를 쓰도록 (임베드 → API 모드)
  sed -i 's|<script src="replay_full.js"[^>]*></script>|<script src="api_loader.js"></script>|' dashboard_full.html
  aws s3 cp dashboard_full.html s3://${DASH_BUCKET}/dashboard_full.html --content-type "text/html"
  aws s3 cp api_loader.js       s3://${DASH_BUCKET}/api_loader.js       --content-type "application/javascript"
  echo "✅ S3 업로드 (API_ENDPOINT=${API_ENDPOINT})"
  # CloudFront 무효화
  CF_ID=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Comment=='${PREFIX} dashboard'].Id" --output text 2>/dev/null)
  if [ -n "$CF_ID" ] && [ "$CF_ID" != "None" ]; then
    aws cloudfront create-invalidation --distribution-id "$CF_ID" --paths "/*" >/dev/null
    CF_URL=$(aws cloudfront list-distributions \
      --query "DistributionList.Items[?Comment=='${PREFIX} dashboard'].DomainName" --output text)
    echo "✅ CloudFront 무효화 → https://${CF_URL}"
  fi
fi

echo ""
echo "════════════════════════════════════════"
echo " 배포 완료"
echo "════════════════════════════════════════"
echo " 다음: bash scripts/load_data.sh   (데이터 적재)"
echo " 대시보드는 CloudFront 무효화 후 2~3분 뒤 접속"
echo "════════════════════════════════════════"
