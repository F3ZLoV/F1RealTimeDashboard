#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  load_data.sh — OpenF1 데이터를 DynamoDB에 적재
#
#  event source mapping(lambda:CreateEventSourceMapping)이 학교 계정에서
#  막혀 KDS→Lambda 자동 적재가 안 되므로, 컨슈머가 DynamoDB에 직접 적재한다.
#  (Firehose→S3 경로를 테스트하려면 scripts/test_firehose.py 별도 실행)
#
#  DRS는 레이스 후반(12:00~)에만 켜지므로, 그 구간을 car+loc 같은 시간대로 적재.
#
#  사용법:  cd ~/F1RealTimeDashboard && bash scripts/load_data.sh
# ══════════════════════════════════════════════════════════════
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "── 의존성 설치 ──"
pip install boto3 requests --quiet

echo ""
echo "── DRS 구간(레이스 후반) 전체 드라이버 적재 ──"
echo "   OpenF1이 간헐적 422를 반환하므로 지수 백오프 재시도 포함"
python3 - <<'PYEOF'
import time, requests
from decimal import Decimal
import boto3
from telemetry import normalize_batch

TABLE = "inhatc-202647019-telemetry"
SESSION = 9165                      # 2023 싱가포르 GP
DRIVERS = [1,2,4,10,11,14,16,20,22,23,24,27,31,40,44,55,63,77,81]
T_START = "2023-09-17T12:00:00"     # DRS 켜지는 후반 구간
T_END   = "2023-09-17T12:15:00"
BASE = "https://api.openf1.org/v1"

ddb = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

def clean(it):
    return {k:(Decimal(str(v)) if isinstance(v,float) else v)
            for k,v in it.items() if v is not None}

def fetch(ep, drv, tries=8):
    params = {"session_key":SESSION, "driver_number":drv,
              "date>":T_START, "date<":T_END}
    for i in range(tries):
        try:
            r = requests.get(f"{BASE}/{ep}", params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(2**i)
    return []

total = 0
for drv in DRIVERS:
    for kind, ep in [("car","car_data"), ("loc","location")]:
        raw = fetch(ep, drv)
        if not raw:
            print(f"  #{drv} {ep}: 실패(데이터 없음)"); continue
        norm,_ = normalize_batch(raw, kind)
        with ddb.batch_writer() as batch:
            for it in norm:
                batch.put_item(Item=clean(it)); total += 1
        print(f"  #{drv} {ep}: {len(norm)}건")
        time.sleep(1)
print(f"\n✅ 총 {total}건 적재 완료")
PYEOF

echo ""
echo "── 적재 확인 ──"
CNT=$(aws dynamodb scan --table-name inhatc-202647019-telemetry --select COUNT --query Count --output text)
echo "DynamoDB 총 레코드: $CNT"
echo ""
echo "다음: 브라우저에서 CloudFront URL 접속 (Ctrl+Shift+R)"
