"""
적재 Lambda — KDS 레코드를 DynamoDB 에 쓴다.

IaC의 aws_lambda_function.ingest 가 이 핸들러를 참조.
트리거: aws_lambda_event_source_mapping (KDS → 이 함수)

레코드 형식(컨슈머가 만든 그대로):
  {pk, sk, type, session_key, driver_number, date, speed/x/y...}

DynamoDB 키 모델:
  PK = pk  (예: "9165#1")
  SK = sk  (예: "car#2023-09-17T12:03:44.658")

필요 권한 (Lambda 실행 Role):
  dynamodb:BatchWriteItem, dynamodb:PutItem
  (KDS 읽기는 event source mapping 이 처리하지만 Role 에도 필요:
   kinesis:GetRecords, GetShardIterator, DescribeStream, ListShards)
"""
import base64
import json
import os
import time
from decimal import Decimal

import boto3

TABLE = os.environ["TABLE_NAME"]
TTL_DAYS = 7  # 실시간 데이터 보존 기간 (이후 자동 삭제)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE)


def _clean(item: dict) -> dict:
    """DynamoDB는 float을 못 받으므로 Decimal로 변환, None 제거."""
    out = {}
    for k, v in item.items():
        if v is None:
            continue
        if isinstance(v, float):
            out[k] = Decimal(str(v))
        else:
            out[k] = v
    return out


def lambda_handler(event, context):
    expire_at = int(time.time()) + TTL_DAYS * 86400
    written = 0

    with table.batch_writer() as batch:
        for record in event["Records"]:
            # KDS payload는 base64 인코딩됨
            payload = base64.b64decode(record["kinesis"]["data"])
            data = json.loads(payload)

            # 단건 또는 배치(리스트) 모두 대응
            items = data if isinstance(data, list) else [data]
            for it in items:
                if "pk" not in it or "sk" not in it:
                    continue
                it["expire_at"] = expire_at  # TTL
                batch.put_item(Item=_clean(it))
                written += 1

    print(f"적재 완료: {written}건 → {TABLE}")
    return {"written": written}
