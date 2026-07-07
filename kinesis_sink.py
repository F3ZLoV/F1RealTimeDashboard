"""
KinesisSink — consumer.py 의 LocalSink 를 대체하는 실제 AWS 버전.

계정 받은 후 사용법:
  consumer.py 상단에서
    from kinesis_sink import KinesisSink
  그리고 main 에서
    sink = LocalSink()
  를
    sink = KinesisSink(stream_name="f1dash-telemetry")  # terraform output 값
  로 바꾸면 끝. 나머지(파싱·배치 로직)는 그대로.

필요 권한 (Fargate 태스크 Role): kinesis:PutRecord, kinesis:PutRecords
"""
import json

import boto3

from consumer import Sink  # 같은 추상 인터페이스 구현


class KinesisSink(Sink):
    def __init__(self, stream_name: str, region: str = "us-east-1"):
        self.client = boto3.client("kinesis", region_name=region)
        self.stream = stream_name

    def put_records(self, records: list):
        if not records:
            return
        # KDS PutRecords 는 호출당 최대 500건
        for i in range(0, len(records), 500):
            chunk = records[i:i + 500]
            entries = [{
                "Data": json.dumps(r).encode("utf-8"),
                "PartitionKey": r["pk"],   # 드라이버별 분산 → 샤드 고름
            } for r in chunk]
            resp = self.client.put_records(StreamName=self.stream, Records=entries)
            # 부분 실패 처리 (스로틀 등) — 실패분만 재시도
            failed = resp.get("FailedRecordCount", 0)
            if failed:
                retry = [entries[j] for j, rec in enumerate(resp["Records"])
                         if "ErrorCode" in rec]
                if retry:
                    self.client.put_records(StreamName=self.stream, Records=retry)
            print(f"  [KinesisSink] {len(chunk)}건 전송 "
                  f"(실패 {failed} 재시도)")
