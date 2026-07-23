"""
Jolpica 데이터 → S3 정적 JSON (CloudFront 서빙용).

왜 DB가 아니라 S3인가:
  - 모든 사용자에게 동일한 읽기 전용 데이터
  - 과거 시즌은 영원히 불변, 현재 시즌만 주 1회 갱신되면 충분
  - CloudFront 엣지 캐시에서 바로 나가므로 Lambda/DynamoDB 홉이 없다
  → 정적 콘텐츠는 CDN, 이게 가장 빠르고 가장 싸다.

Jolpica 는 limit 상한이 100 이라 시즌 전체 결과(24전 × 20명 = 480행)를
한 번에 못 받는다. 여기서 오프셋 페이지네이션으로 모아 한 파일로 굽는다.

출력 (대시보드 버킷):
  data/results-{season}.json     시즌 전체 레이스 결과
  data/schedule-{season}.json    시즌 일정

사용 (CloudShell):
  python3 scripts/build_data_cache.py            # 2021~올해
  python3 scripts/build_data_cache.py 2024 2025  # 특정 연도만
"""
import gzip
import json
import sys
import time
import urllib.request
from datetime import datetime

import boto3

JOLPICA = "https://api.jolpi.ca/ergast/f1"
ACCT = "269578498605"
PREFIX = "inhatc-202647019"
BUCKET = f"{PREFIX}-dashboard-{ACCT}"
DATA_PREFIX = "data"
FIRST_SEASON = 2021
PAGE = 100  # Jolpica limit 상한

s3 = boto3.client("s3")


def fetch(path, params=""):
    url = f"{JOLPICA}/{path}?{params}" if params else f"{JOLPICA}/{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            wait = 2 ** attempt
            print(f"    재시도 {attempt+1}/5 ({e}) — {wait}s 대기")
            time.sleep(wait)
    raise RuntimeError(f"조회 실패: {url}")


def season_results(season):
    """오프셋 페이지네이션으로 시즌 전체 결과를 모아 라운드별로 병합."""
    races = {}   # round → race dict
    offset = 0
    total = None

    while True:
        data = fetch(f"{season}/results/", f"limit={PAGE}&offset={offset}")
        mr = data["MRData"]
        if total is None:
            total = int(mr.get("total", 0))
            print(f"  총 {total}행")
        for race in mr["RaceTable"]["Races"]:
            rnd = race["round"]
            if rnd in races:
                # 페이지 경계에서 같은 레이스가 쪼개져 오므로 결과만 이어붙인다
                races[rnd]["Results"].extend(race.get("Results", []))
            else:
                races[rnd] = race
        offset += PAGE
        if offset >= total:
            break
        time.sleep(0.3)  # Jolpica 배려 (시간당 500회 제한)

    out = sorted(races.values(), key=lambda r: int(r["round"]))
    for r in out:
        r["Results"].sort(key=lambda x: int(x["position"]))
    print(f"  {len(out)}개 라운드 조립 완료")
    return out


def season_qualifying(season):
    """예선도 결과와 같은 방식으로 페이지네이션해 모은다."""
    races = {}
    offset = 0
    total = None
    while True:
        data = fetch(f"{season}/qualifying/", f"limit={PAGE}&offset={offset}")
        mr = data["MRData"]
        if total is None:
            total = int(mr.get("total", 0))
            if total == 0:
                return []
            print(f"  예선 총 {total}행")
        for race in mr["RaceTable"]["Races"]:
            rnd = race["round"]
            if rnd in races:
                races[rnd]["QualifyingResults"].extend(race.get("QualifyingResults", []))
            else:
                races[rnd] = race
        offset += PAGE
        if offset >= total:
            break
        time.sleep(0.3)

    out = sorted(races.values(), key=lambda r: int(r["round"]))
    for r in out:
        r["QualifyingResults"].sort(key=lambda x: int(x["position"]))
    return out


def season_schedule(season):
    data = fetch(f"{season}/races/", "limit=100")
    return data["MRData"]["RaceTable"]["Races"]


def put(name, payload):
    """gzip 으로 올리고 Content-Encoding 을 붙여 브라우저가 알아서 풀게 한다."""
    body = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6
    )
    key = f"{DATA_PREFIX}/{name}.json"
    s3.put_object(
        Bucket=BUCKET, Key=key, Body=body,
        ContentType="application/json",
        ContentEncoding="gzip",
        CacheControl="public,max-age=3600",
    )
    print(f"  → s3://{BUCKET}/{key}  ({len(body)/1024:.0f} KB)")


def main():
    this_year = datetime.now().year
    if len(sys.argv) > 1:
        seasons = [int(a) for a in sys.argv[1:]]
    else:
        seasons = list(range(FIRST_SEASON, this_year + 1))

    for season in seasons:
        print(f"\n=== {season} ===")
        try:
            results = season_results(season)
            if results:
                put(f"results-{season}", results)
            quali = season_qualifying(season)
            if quali:
                put(f"qualifying-{season}", quali)
            schedule = season_schedule(season)
            if schedule:
                put(f"schedule-{season}", schedule)
        except Exception as e:
            print(f"  ⚠️ {season} 실패: {e}")

    print("\n완료. CloudFront 무효화가 필요하면:")
    print(f"  aws cloudfront create-invalidation --distribution-id <ID> --paths '/{DATA_PREFIX}/*'")


if __name__ == "__main__":
    main()