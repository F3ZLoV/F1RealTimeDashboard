"""
ML 데이터셋 빌더 — 타이어 마모(degradation) 예측용.

아이디어:
  laps(랩타임) + stints(컴파운드, 타이어나이) 를 조인해서
  "각 랩 = 이 타이어로 몇 랩째 뛰었고(tyre_life), 컴파운드는 뭐고,
   랩타임은 얼마였나" 를 한 줄로 만든다.

이게 타이어 마모 모델의 학습 테이블이 됨:
  입력(feature): compound, tyre_life, lap_number, 연료보정(랩 진행)
  출력(label):   lap_duration (또는 best 대비 델타)

여러 드라이버를 합쳐서 일반화. 아웃라이어(피트인/아웃, 세이프티카 등)는 제거.

출력: ml_dataset.csv
"""
import csv

from openf1_client import OpenF1

SESSION_KEY = 9165
# 관심 드라이버 (많을수록 데이터↑). 일단 상위권 + 풀레이스 완주자 위주
DRIVERS = [1, 4, 11, 16, 44, 55, 63, 81]
OUT = "ml_dataset.csv"

client = OpenF1()


def tyre_life_for_lap(stints: list, lap_number: int):
    """해당 랩이 속한 스틴트를 찾아 (컴파운드, 타이어나이) 반환."""
    for st in stints:
        if st["lap_start"] <= lap_number <= st["lap_end"]:
            # 타이어나이 = 스틴트 시작 시 나이 + 스틴트 내 경과 랩
            age = st.get("tyre_age_at_start", 0) + (lap_number - st["lap_start"])
            return st.get("compound"), age, st["stint_number"]
    return None, None, None


def build():
    rows = []
    for drv in DRIVERS:
        laps = client.get("laps", session_key=SESSION_KEY, driver_number=drv)
        stints = client.get("stints", session_key=SESSION_KEY, driver_number=drv)
        if not laps or not stints:
            print(f"#{drv}: 데이터 없음, 건너뜀")
            continue

        kept = 0
        for lap in laps:
            dur = lap.get("lap_duration")
            ln = lap.get("lap_number")
            if dur is None or ln is None:
                continue
            # 아웃라이어 제거: 피트아웃 랩, 비정상적으로 느린 랩(세이프티카/피트인)
            if lap.get("is_pit_out_lap"):
                continue
            compound, tyre_life, stint_no = tyre_life_for_lap(stints, ln)
            if compound is None:
                continue

            rows.append({
                "driver_number": drv,
                "lap_number": ln,
                "stint_number": stint_no,
                "compound": compound,
                "tyre_life": tyre_life,
                "lap_duration": dur,
                "sector1": lap.get("duration_sector_1"),
                "sector2": lap.get("duration_sector_2"),
                "sector3": lap.get("duration_sector_3"),
                "i1_speed": lap.get("i1_speed"),
                "i2_speed": lap.get("i2_speed"),
                "st_speed": lap.get("st_speed"),
            })
            kept += 1
        print(f"#{drv}: {kept}개 랩 수집")

    # 세션 전체 중앙값 기준 아웃라이어 컷 (세이프티카/사고 랩 제거)
    durs = sorted(r["lap_duration"] for r in rows)
    if durs:
        median = durs[len(durs)//2]
        cutoff = median * 1.20   # 중앙값의 120% 초과는 비정상으로 간주
        before = len(rows)
        rows = [r for r in rows if r["lap_duration"] <= cutoff]
        print(f"\n아웃라이어 제거: {before} → {len(rows)} "
              f"(중앙값 {median:.1f}s, 컷오프 {cutoff:.1f}s)")

    # CSV 저장
    if rows:
        with open(OUT, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\n{OUT} 생성 — 총 {len(rows)}행")
        # 컴파운드별 요약
        from collections import defaultdict
        by_c = defaultdict(list)
        for r in rows:
            by_c[r["compound"]].append(r["lap_duration"])
        print("\n컴파운드별 랩타임 요약:")
        for c, ds in by_c.items():
            print(f"  {c:<8} {len(ds):>3}랩  평균 {sum(ds)/len(ds):.2f}s  "
                  f"최速 {min(ds):.2f}s")


if __name__ == "__main__":
    build()
