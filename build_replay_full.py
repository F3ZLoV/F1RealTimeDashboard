"""
풀 리플레이 빌더 — 전체 드라이버 + 앞 N랩 + 타이어 마모 모델 예측 포함.

기존 build_replay.py 의 확장판:
  - 전체 20명 처리 (관심 드라이버 한정 X)
  - 앞 MAX_LAPS_SECONDS 구간만 (고해상도 3.7Hz 유지)
  - 각 드라이버의 스틴트 정보로 '현재 타이어 상태' 트랙 추가
  - 학습된 모델(tyre_model.pt)로 마모 곡선/현재 예측을 미리 계산해 임베드
    → 대시보드가 추론 없이 바로 표시 (나중에 SageMaker 엔드포인트로 대체될 자리)

출력: replay_full.js  (dashboard_full.html 이 읽음)

사전조건: train_tyre_model.py 먼저 실행 (tyre_model.pt, scaler.json 필요)
"""
import json
from bisect import bisect_left
from datetime import datetime

import numpy as np
import torch

from openf1_client import OpenF1
from telemetry import normalize_batch
from train_tyre_model import TyreModel, COMPOUNDS

SESSION_KEY = 9165
MAX_LAPS_SECONDS = 2000   # 앞 ~20랩 (싱가포르 랩 ~100s × 20)
DS_HZ = None              # None=다운샘플 안 함(3.7Hz 풀해상도). 숫자 주면 그 Hz로 줄임
OUT = "replay_full.js"

client = OpenF1()

# ── 모델 로드 (마모 예측 임베드용) ──
with open("scaler.json") as f:
    sc = json.load(f)
MEAN, STD = np.array(sc["mean"]), np.array(sc["std"])
model = TyreModel(len(COMPOUNDS) + 2)
model.load_state_dict(torch.load("tyre_model.pt"))
model.eval()


def predict_lap(compound, tyre_life, lap_number):
    if compound not in COMPOUNDS:
        return None
    oh = [1.0 if compound == c else 0.0 for c in COMPOUNDS]
    num = [(tyre_life - MEAN[0]) / STD[0], (lap_number - MEAN[1]) / STD[1]]
    x = torch.tensor([oh + num], dtype=torch.float32)
    with torch.no_grad():
        return round(model(x).item(), 2)


def to_ts(d):
    return datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp()


def nearest(car, car_ts, t):
    i = bisect_left(car_ts, t)
    if i == 0: return car[0]
    if i >= len(car): return car[-1]
    return car[i-1] if abs(car_ts[i-1]-t) <= abs(car_ts[i]-t) else car[i]


def stint_at_lap(stints, lap_number):
    for st in stints:
        ls, le = st.get("lap_start"), st.get("lap_end")
        if ls is None:
            continue
        if le is None:                 # 미완주 등으로 lap_end 없으면 마지막 스틴트로 간주
            le = ls + 99
        if ls <= lap_number <= le:
            age = (st.get("tyre_age_at_start") or 0) + (lap_number - ls)
            return st.get("compound"), age
    return None, None


def build_driver(drv, meta):
    car_raw = client.get("car_data", session_key=SESSION_KEY, driver_number=drv)
    loc_raw = client.get("location", session_key=SESSION_KEY, driver_number=drv)
    laps = client.get("laps", session_key=SESSION_KEY, driver_number=drv)
    stints = client.get("stints", session_key=SESSION_KEY, driver_number=drv)

    car, _ = normalize_batch(car_raw, "car")
    loc, _ = normalize_batch(loc_raw, "loc")
    if not loc:
        return None
    car.sort(key=lambda r: r["date"])
    loc.sort(key=lambda r: r["date"])
    car_ts = [to_ts(r["date"]) for r in car]

    # 랩 시작 시각(절대 타임스탬프) → 몇 랩째인지 매핑
    lap_starts = sorted([(to_ts(l["date_start"]), l["lap_number"])
                         for l in laps if l.get("date_start")])

    def lap_at(ts):
        ln = 0
        for lts, n in lap_starts:
            if ts >= lts:
                ln = n
            else:
                break
        return ln if ln > 0 else 1

    # 기준 시점 = 레이스 실제 시작(랩1 date_start). 없으면 location 첫 프레임.
    t0 = lap_starts[0][0] if lap_starts else to_ts(loc[0]["date"])

    frames = []
    last_emit = -999
    ds_gap = (1.0 / DS_HZ) if DS_HZ else 0
    for p in loc:
        ts = to_ts(p["date"]); rel = ts - t0
        if rel < 0:          # 레이스 시작 전(차고/포메이션) 데이터 제외
            continue
        if rel > MAX_LAPS_SECONDS:
            break
        if DS_HZ and (rel - last_emit) < ds_gap:
            continue
        last_emit = rel
        c = nearest(car, car_ts, ts)
        ln = lap_at(ts)
        comp, age = stint_at_lap(stints, ln)
        frames.append({
            "t": round(rel, 2), "x": p["x"], "y": p["y"],
            "speed": c.get("speed"), "gear": c.get("n_gear"),
            "throttle": c.get("throttle"), "brake": c.get("brake"),
            "drs": c.get("drs"), "lap": ln,
            "comp": comp, "age": age,
        })

    # 이 드라이버의 마모 곡선(현재 컴파운드 기준 0~35랩) 미리 계산
    cur_comp = frames[-1]["comp"] if frames else None
    deg_curve = None
    if cur_comp:
        deg_curve = [predict_lap(cur_comp, a, 15) for a in range(0, 36)]

    return {
        "number": drv,
        "acronym": meta.get("name_acronym", str(drv)),
        "name": meta.get("full_name", ""),
        "team": meta.get("team_name", ""),
        "colour": "#" + meta.get("team_colour", "888888"),
        "frames": frames,
        "deg_curve": deg_curve,   # 인덱스=타이어나이, 값=예측 랩타임
    }


def main():
    drivers_meta = {d["driver_number"]: d
                    for d in client.get("drivers", session_key=SESSION_KEY)}
    out = {"session_key": SESSION_KEY, "drivers": [], "compounds": COMPOUNDS}
    all_x, all_y = [], []

    for drv, meta in sorted(drivers_meta.items()):
        d = build_driver(drv, meta)
        if not d:
            print(f"#{drv}: skip (no data)")
            continue
        out["drivers"].append(d)
        all_x += [f["x"] for f in d["frames"]]
        all_y += [f["y"] for f in d["frames"]]
        cc = d["frames"][-1]["comp"] if d["frames"] else "?"
        print(f"#{drv:>2} {d['acronym']}: {len(d['frames'])} 프레임  (현재 {cc})")

    out["bounds"] = {"minX": min(all_x), "maxX": max(all_x),
                     "minY": min(all_y), "maxY": max(all_y)}

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("window.REPLAY = ")
        json.dump(out, f, ensure_ascii=False)
        f.write(";")
    total = sum(len(d["frames"]) for d in out["drivers"])
    print(f"\n{OUT} 생성 — {len(out['drivers'])}명, 총 {total:,} 프레임")
    print("dashboard_full.html 을 브라우저로 열면 됨.")


if __name__ == "__main__":
    main()
