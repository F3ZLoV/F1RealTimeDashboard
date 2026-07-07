"""
Fargate 컨슈머 (1차: 과거 데이터 리플레이 모드).

계정 받기 전 단계라 실제 KDS 대신 '싱크(sink)'를 추상화해서,
지금은 콘솔/파일로 출력하고 계정 오면 KinesisSink 로 갈아끼우기만 하면 됨.

흐름:
  OpenF1(과거) → 파싱/노이즈필터(telemetry.py) → Sink(put_records)

계정 오면 바뀌는 것:
  - LocalSink → KinesisSink (boto3 put_records)
  - 데이터 소스: REST 폴링 → MQTT/WSS 구독 (replay → live)
나머지(파싱·키 모델·배치 로직)는 그대로 재사용.
"""
import json
import os
import time
from abc import ABC, abstractmethod

from openf1_client import OpenF1
from telemetry import normalize_batch

SESSION_KEY = 9165       # 2023 Singapore GP - Race
DRIVER_NUMBERS = [1, 4]  # 관심 드라이버만 (비용 절약). 전체는 drivers 조회해서 확장
BATCH_SIZE = 500         # KDS PutRecords 최대 500건/호출


# ── Sink 추상화 ────────────────────────────────────────────────
class Sink(ABC):
    @abstractmethod
    def put_records(self, records: list):
        ...


class LocalSink(Sink):
    """계정 없을 때: 파일로 떨궈서 검증. (KDS 대체)"""
    def __init__(self, out_dir="kds_out"):
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.count = 0

    def put_records(self, records: list):
        if not records:
            return
        path = os.path.join(self.out_dir, f"batch_{self.count:05d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False)
        self.count += 1
        print(f"  [LocalSink] {len(records)}건 → {path}")


# 계정 오면 아래 주석 해제해서 LocalSink 대신 사용:
#
# import boto3
# class KinesisSink(Sink):
#     def __init__(self, stream_name, region="us-east-1"):
#         self.client = boto3.client("kinesis", region_name=region)
#         self.stream = stream_name
#     def put_records(self, records):
#         for i in range(0, len(records), 500):  # KDS 최대 500건/호출
#             chunk = records[i:i+500]
#             entries = [{
#                 "Data": json.dumps(r).encode("utf-8"),
#                 "PartitionKey": r["pk"],   # 드라이버별 분산
#             } for r in chunk]
#             self.client.put_records(StreamName=self.stream, Records=entries)


# ── 컨슈머 ────────────────────────────────────────────────────
def replay(sink: Sink):
    client = OpenF1()
    total_sent = total_dropped = 0

    for drv in DRIVER_NUMBERS:
        print(f"\n드라이버 #{drv} 처리 중...")
        for kind, endpoint in [("car", "car_data"), ("loc", "location")]:
            raw = client.get(endpoint, session_key=SESSION_KEY, driver_number=drv)
            norm, dropped = normalize_batch(raw, kind)
            total_dropped += dropped
            print(f"  {endpoint}: 원본 {len(raw):,} → 유효 {len(norm):,} "
                  f"(노이즈 {dropped:,} 제거)")
            # 배치로 sink에 전송 (KDS PutRecords 시뮬레이션)
            for i in range(0, len(norm), BATCH_SIZE):
                sink.put_records(norm[i:i + BATCH_SIZE])
                total_sent += len(norm[i:i + BATCH_SIZE])

    print(f"\n{'='*50}")
    print(f"전송 {total_sent:,}건 / 노이즈 제거 {total_dropped:,}건")


if __name__ == "__main__":
    sink = LocalSink()
    t0 = time.time()
    replay(sink)
    print(f"소요 {time.time()-t0:.1f}s")
