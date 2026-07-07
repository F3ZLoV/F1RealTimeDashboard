"""
OpenF1 데이터 탐색 스크립트.

목적:
  1) 어떤 세션/드라이버가 있는지 확인
  2) car_data / location / laps / stints 의 실제 필드 구조 확인
  3) 실제 데이터 샘플링 레이트(records/sec) 측정 → 아키텍처/비용 검증
  4) 샘플 JSON을 ./samples/ 에 저장 (VS Code에서 직접 열어보기 용)

사용:
  pip install -r requirements.txt
  python explore.py

다른 세션을 보고 싶으면 아래 SESSION_KEY / DRIVER_NUMBER 만 바꾸면 됨.
"""
import json
import os
from datetime import datetime, timedelta

from openf1_client import OpenF1

# ── 탐색 대상 (2023 싱가포르 GP 레이스, 무료 과거 데이터) ──────────────
# 다른 세션 키를 찾으려면 print_available_sessions() 출력 참고
SESSION_KEY = 9165       # 2023 Singapore GP - Race
DRIVER_NUMBER = 1        # Max Verstappen
SAMPLE_DIR = "samples"

client = OpenF1()


def save_sample(name: str, data: list, n: int = 3):
    """샘플 데이터를 파일로 저장하고 첫 n개 레코드 구조를 출력."""
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    path = os.path.join(SAMPLE_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data[:50], f, indent=2, ensure_ascii=False)
    print(f"\n{'='*60}\n[{name}]  총 {len(data):,}개 레코드  →  {path} 저장")
    if data:
        print(f"필드: {list(data[0].keys())}")
        print(f"샘플 레코드:")
        print(json.dumps(data[0], indent=2, ensure_ascii=False))
    return data


def print_available_sessions():
    """2023년 세션 목록 일부 출력 — 다른 세션 키 찾을 때 참고."""
    print("\n### 2023 시즌 세션 일부 (다른 데이터 보고 싶을 때 참고) ###")
    sessions = client.sessions(year=2023)
    for s in sessions[:15]:
        print(f"  session_key={s['session_key']:>5}  "
              f"{s.get('country_name',''):<15} "
              f"{s.get('session_name',''):<12} {s.get('date_start','')[:10]}")
    print(f"  ... 총 {len(sessions)}개 세션\n")


def explore_drivers():
    drivers = client.drivers(session_key=SESSION_KEY)
    save_sample("drivers", drivers)
    print("\n이 세션의 드라이버:")
    for d in drivers:
        print(f"  #{d['driver_number']:>2}  {d.get('name_acronym','')}  "
              f"{d.get('full_name',''):<22} {d.get('team_name','')}")
    return drivers


def explore_car_data():
    """텔레메트리 — 속도/스로틀/브레이크/기어/RPM/DRS. 약 3.7Hz."""
    # 레이스 시작 직후 30초 구간만 샘플로 (전체는 너무 큼)
    data = client.car_data(session_key=SESSION_KEY, driver_number=DRIVER_NUMBER)
    save_sample("car_data", data)
    measure_rate("car_data", data)
    return data


def explore_location():
    """트랙맵용 X/Y/Z 좌표."""
    data = client.location(session_key=SESSION_KEY, driver_number=DRIVER_NUMBER)
    save_sample("location", data)
    measure_rate("location", data)
    # 좌표 범위 출력 (트랙맵 스케일 가늠)
    xs = [p["x"] for p in data if p.get("x") is not None]
    ys = [p["y"] for p in data if p.get("y") is not None]
    if xs and ys:
        print(f"\n트랙 좌표 범위: x[{min(xs)}, {max(xs)}]  y[{min(ys)}, {max(ys)}]")
    return data


def explore_laps():
    data = client.laps(session_key=SESSION_KEY, driver_number=DRIVER_NUMBER)
    save_sample("laps", data)
    # 랩타임 요약
    print("\n랩타임 (앞 10랩):")
    for lap in data[:10]:
        dur = lap.get("lap_duration")
        print(f"  Lap {lap.get('lap_number'):>2}: "
              f"{dur if dur else '—'}  "
              f"S1={lap.get('duration_sector_1')} "
              f"S2={lap.get('duration_sector_2')} "
              f"S3={lap.get('duration_sector_3')}")
    return data


def explore_stints():
    """타이어 스틴트 — ML 타이어 마모 모델의 핵심 라벨."""
    data = client.stints(session_key=SESSION_KEY, driver_number=DRIVER_NUMBER)
    save_sample("stints", data)
    print("\n타이어 스틴트:")
    for st in data:
        print(f"  스틴트 {st.get('stint_number')}: "
              f"{st.get('compound')}  "
              f"랩 {st.get('lap_start')}~{st.get('lap_end')}  "
              f"시작 타이어나이={st.get('tyre_age_at_start')}")
    return data


def measure_rate(name: str, data: list):
    """date 필드로 실제 샘플링 레이트(records/sec) 측정 → 볼륨 추정."""
    dates = [d["date"] for d in data if d.get("date")]
    if len(dates) < 2:
        return
    fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
    try:
        parsed = sorted(datetime.fromisoformat(x.replace("Z", "+00:00")) for x in dates)
    except Exception:
        return
    span = (parsed[-1] - parsed[0]).total_seconds()
    if span <= 0:
        return
    rate = len(parsed) / span
    print(f"\n  ↳ [{name}] {len(parsed):,}개 / {span:,.0f}초 = "
          f"드라이버당 약 {rate:.2f} records/sec")
    # 전체 그리드(20명) 환산 → KDS 샤드 sizing 검증
    grid_rate = rate * 20
    print(f"    전체 20명 환산: 약 {grid_rate:.0f} records/sec "
          f"(KDS 1샤드 = 1000 rec/s 이므로 {'1샤드로 충분' if grid_rate < 1000 else '샤드 추가 필요'})")


def main():
    print("OpenF1 데이터 탐색 시작\n")
    print_available_sessions()
    explore_drivers()
    explore_laps()
    explore_stints()
    explore_car_data()
    explore_location()
    print(f"\n{'='*60}")
    print("완료. ./samples/ 폴더에 각 엔드포인트 샘플 JSON 저장됨.")
    print("VS Code에서 samples/*.json 열어서 필드 구조 직접 확인해봐.")


if __name__ == "__main__":
    main()
