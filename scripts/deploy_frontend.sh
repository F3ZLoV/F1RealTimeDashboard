#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  deploy_frontend.sh — Next.js 정적 빌드(out/)를 S3 + CloudFront 로 배포
#
#  전제: 로컬에서 `npm run build` 로 out/ 을 만든 뒤 CloudShell 로 옮겨온 상태
#        (CloudShell Actions → Upload file 로 out.zip 업로드 후 unzip)
#
#  캐시 전략:
#    _next/static/**  → 파일명에 해시가 있어 영구 캐시 (1년, immutable)
#    나머지(html 등)  → 매번 검증 (no-cache) — 배포 즉시 반영
#
#  사용법:  bash scripts/deploy_frontend.sh /path/to/out
# ══════════════════════════════════════════════════════════════
set -uo pipefail

ACCT=269578498605
PREFIX=inhatc-202647019
BUCKET="${PREFIX}-dashboard-${ACCT}"
OUT_DIR="${1:-./out}"

echo "현재 계정: $(aws sts get-caller-identity --query Arn --output text)"

if [ ! -f "$OUT_DIR/index.html" ]; then
  echo "❌ $OUT_DIR/index.html 이 없습니다."
  echo "   로컬에서 'npm run build' 후 out/ 을 업로드했는지 확인하세요."
  exit 1
fi

echo "── 1) 해시 자산 업로드 (영구 캐시) ──"
aws s3 sync "$OUT_DIR/_next/static" "s3://${BUCKET}/_next/static" \
  --cache-control "public,max-age=31536000,immutable" \
  --delete

echo "── 2) 나머지 업로드 (즉시 반영) ──"
aws s3 sync "$OUT_DIR" "s3://${BUCKET}" \
  --exclude "_next/static/*" \
  --cache-control "public,max-age=0,must-revalidate" \
  --delete

echo "── 3) CloudFront 무효화 ──"
CF_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment=='${PREFIX} dashboard'].Id" \
  --output text 2>/dev/null)

if [ -n "$CF_ID" ] && [ "$CF_ID" != "None" ]; then
  aws cloudfront create-invalidation --distribution-id "$CF_ID" --paths "/*" >/dev/null
  CF_URL=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Comment=='${PREFIX} dashboard'].DomainName" \
    --output text)
  echo "✅ 배포 완료 → https://${CF_URL}"
  echo "   (무효화 반영까지 2~3분)"
else
  echo "⚠️ CloudFront 배포를 찾지 못했습니다. terraform apply 를 먼저 실행하세요."
fi
