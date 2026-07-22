#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  00_setup_cloudshell.sh — CloudShell 재시작 후 환경 복구
#
#  CloudShell은 재시작 시 /tmp와 환경변수가 날아가고, 홈은 1GB 쿼터가 있다.
#  terraform provider(~500MB)가 홈을 넘치게 하므로 캐시를 /tmp에 둔다.
#
#  사용법:  bash scripts/00_setup_cloudshell.sh
#          그 다음 매 세션: export PATH=/tmp:$PATH
# ══════════════════════════════════════════════════════════════
set -uo pipefail

echo "── 계정 확인 ──"
ARN=$(aws sts get-caller-identity --query Arn --output text)
echo "$ARN"
case "$ARN" in
  *inhatc-202647019*) echo "✅ OK" ;;
  *) echo "⚠️ 계정 다름. 필요시: rm -f ~/.aws/credentials ~/.aws/config" ;;
esac

echo ""
echo "── terraform 설치 (/tmp, 홈 쿼터 회피) ──"
if command -v terraform >/dev/null 2>&1; then
  echo "이미 설치됨: $(terraform version | head -1)"
else
  cd /tmp
  curl -s -o tf.zip https://releases.hashicorp.com/terraform/1.9.8/terraform_1.9.8_linux_amd64.zip
  unzip -o -q tf.zip
  rm -f tf.zip LICENSE.txt
  echo "설치됨: $(/tmp/terraform version | head -1)"
fi

echo ""
echo "── 환경변수 (매 세션 필요) ──"
echo 'export PATH=/tmp:$PATH'
echo 'export TF_PLUGIN_CACHE_DIR=/tmp/tfcache'
mkdir -p /tmp/tfcache

echo ""
echo "── pip 의존성 ──"
pip install boto3 requests --quiet && echo "✅ boto3, requests"

echo ""
echo "── 홈 용량 확인 (1GB 쿼터) ──"
du -sh ~ 2>/dev/null
echo ""
echo "준비 완료. 이제:"
echo "  export PATH=/tmp:\$PATH && export TF_PLUGIN_CACHE_DIR=/tmp/tfcache"
echo "  bash scripts/deploy.sh"
