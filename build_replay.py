"""
대시보드용 리플레이 데이터 빌더.

목적:
  car_data(속도/기어/브레이크 등)와 location(x,y)을 시간축으로 병합하여
  "각 시점마다 차가 어디에 있고 어떤 상태인지"를 담은 단일 JSON 생성.

핵심 처리 (실데이터에서 발견한 이슈 대응):
  - car_data 와 location 의 타임스탬프가 미세하게 다름 → 근접 조인(nearest)
  - 차고/정지 노이즈는 telemetry.normalize_* 로 이미 제거됨
  - 출력은 location 기준(트랙 위 위치)으로, 각 위치에 가장 가까운 car_data 상태를 붙임

출력: replay_data.json  (dashboard.html 이 읽음)

소스 선택:
  - 기본: OpenF1 API 직접 호출(과거 데이터)
  - 계정/실시간 가면 이 빌더는 Lambda 조회 API로 대체됨
"""
import json
from bisect import bisect_left
from datetime import datetime

from openf1_client import OpenF1
from telemetry import normalize_batch

SESSION_KEY = 9165
DRIVERS = [1, 4]          # VER, NOR
MAX_LAPS_SECONDS = 600    # 앞 10분만 (프로토타입용; 전체는 너무 김)
START_OFFSET = 1200       # 시작 20분 지점부터 (세이프티카 끝나고 DRS 활성 구간)
OUT = "replay_data.js"    # JS 파일로 출력 → file:// 로 열어도 CORS 없이 로드

client = OpenF1()


def to_ts(date_str: str) -> float:
    return datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp()


def nearest_car(car_sorted, car_ts, target_ts):
    """target_ts 에 가장 가까운 car_data 레코드 반환."""
    i = bisect_left(car_ts, target_ts)
    if i == 0:
        return car_sorted[0]
    if i >= len(car_sorted):
        return car_sorted[-1]
    before, after = car_sorted[i - 1], car_sorted[i]
    if abs(car_ts[i - 1] - target_ts) <= abs(car_ts[i] - target_ts):
        return before
    return after


def build_driver(drv: int):
    car_raw = client.get("car_data", session_key=SESSION_KEY, driver_number=drv)
    loc_raw = client.get("location", session_key=SESSION_KEY, driver_number=drv)
    car, _ = normalize_batch(car_raw, "car")
    loc, _ = normalize_batch(loc_raw, "loc")

    car.sort(key=lambda r: r["date"])
    loc.sort(key=lambda r: r["date"])
    car_ts = [to_ts(r["date"]) for r in car]

    # 시작 시점 기준 상대 시간(초)으로 변환 + 근접 조인
    if not loc:
        return []
    t0 = to_ts(loc[0]["date"])
    frames = []
    for p in loc:
        ts = to_ts(p["date"])
        rel = ts - t0
        if rel > MAX_LAPS_SECONDS:
            break
        c = nearest_car(car, car_ts, ts)
        frames.append({
            "t": round(rel, 2),
            "x": p["x"], "y": p["y"],
            "speed": c.get("speed"), "gear": c.get("n_gear"),
            "throttle": c.get("throttle"), "brake": c.get("brake"),
            "drs": c.get("drs"),
        })
    return frames


def main():
    drivers_meta = client.get("drivers", session_key=SESSION_KEY)
    meta = {d["driver_number"]: d for d in drivers_meta}

    out = {"session_key": SESSION_KEY, "drivers": []}
    all_x, all_y = [], []
    for drv in DRIVERS:
        frames = build_driver(drv)
        m = meta.get(drv, {})
        out["drivers"].append({
            "number": drv,
            "acronym": m.get("name_acronym", str(drv)),
            "name": m.get("full_name", ""),
            "team": m.get("team_name", ""),
            "colour": "#" + m.get("team_colour", "888888"),
            "frames": frames,
        })
        all_x += [f["x"] for f in frames]
        all_y += [f["y"] for f in frames]
        print(f"#{drv} {m.get('name_acronym','')}: {len(frames)} 프레임")

    # 트랙 좌표 범위(대시보드 스케일링용)
    out["bounds"] = {"minX": min(all_x), "maxX": max(all_x),
                     "minY": min(all_y), "maxY": max(all_y)}

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("window.REPLAY = ")
        json.dump(out, f, ensure_ascii=False)
        f.write(";")
    print(f"\n{OUT} 생성 완료. dashboard.html 을 브라우저로 열면 됨.")


if __name__ == "__main__":
    main()
