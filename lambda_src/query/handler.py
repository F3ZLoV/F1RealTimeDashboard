"""
조회 Lambda — 대시보드 API 백엔드.

IaC의 aws_lambda_function.query 가 이 핸들러를 참조.
경로: GET /telemetry?session=9165&driver=1&since=<iso>&type=car

대시보드가 이걸 호출해 특정 드라이버의 최근 텔레메트리를 받아간다.
(로컬 프로토타입의 임베드 JS 를 실시간 fetch 로 대체하는 자리)

DynamoDB 조회:
  PK = "{session}#{driver}", SK = "{type}#{date}" 범위 쿼리
  → 한 파티션에서 시간순 텔레메트리를 효율적으로 가져옴

필요 권한 (Lambda 실행 Role): dynamodb:Query
"""
import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

TABLE = os.environ["TABLE_NAME"]
table = boto3.resource("dynamodb").Table(TABLE)


def _ser(o):
    """Decimal → 숫자 직렬화."""
    if isinstance(o, Decimal):
        return int(o) if o % 1 == 0 else float(o)
    raise TypeError


def lambda_handler(event, context):
    qs = event.get("queryStringParameters") or {}
    session = qs.get("session", "9165")
    driver = qs.get("driver", "1")
    rec_type = qs.get("type", "car")     # car | loc
    since = qs.get("since")              # ISO 타임스탬프(옵션)
    limit = int(qs.get("limit", "500"))

    pk = f"{session}#{driver}"
    sk_prefix = f"{rec_type}#"
    cond = Key("pk").eq(pk)
    if since:
        cond = cond & Key("sk").gte(f"{rec_type}#{since}")
    else:
        cond = cond & Key("sk").begins_with(sk_prefix)

    resp = table.query(
        KeyConditionExpression=cond,
        Limit=limit,
        ScanIndexForward=True,   # 시간 오름차순
    )

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(resp.get("Items", []), default=_ser),
    }
