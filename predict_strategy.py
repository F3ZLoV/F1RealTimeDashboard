"""
전략 예측 — 학습된 타이어 모델로 두 가지 출력 생성.

  1) 절대 랩타임:  특정 (컴파운드, 타이어나이) 에서 예상 랩타임
  2) 마모율:       tyre_life 를 1랩씩 굴렸을 때의 랩타임 증가분
  + 간단한 피트 윈도우 시뮬레이션 (언더컷/오버컷 감각)

train_tyre_model.py 를 먼저 돌려 tyre_model.pt / scaler.json 이 있어야 함.
"""
import json

import numpy as np
import torch

from train_tyre_model import TyreModel, COMPOUNDS

with open("scaler.json") as f:
    sc = json.load(f)
MEAN = np.array(sc["mean"])
STD = np.array(sc["std"])

model = TyreModel(len(COMPOUNDS) + 2)
model.load_state_dict(torch.load("tyre_model.pt"))
model.eval()


def predict(compound: str, tyre_life: int, lap_number: int) -> float:
    """절대 랩타임 예측."""
    oh = [1.0 if compound == c else 0.0 for c in COMPOUNDS]
    num = [(tyre_life - MEAN[0]) / STD[0], (lap_number - MEAN[1]) / STD[1]]
    x = torch.tensor([oh + num], dtype=torch.float32)
    with torch.no_grad():
        return model(x).item()


def deg_rate(compound: str, tyre_life: int, lap_number: int) -> float:
    """마모율 = 다음 랩 - 현재 랩 (랩당 손실 초)."""
    return predict(compound, tyre_life + 1, lap_number + 1) - \
           predict(compound, tyre_life, lap_number)


def stint_cost(compound: str, start_life: int, start_lap: int, n_laps: int) -> float:
    """스틴트 누적 랩타임 (n_laps 동안)."""
    return sum(predict(compound, start_life + i, start_lap + i) for i in range(n_laps))


def main():
    print("=== 1) 절대 랩타임 예측 ===")
    for c in COMPOUNDS:
        for tl in [0, 10, 20, 30]:
            print(f"  {c:<7} {tl:>2}랩째 (레이스 20랩 시점): "
                  f"{predict(c, tl, 20):.2f}s")

    print("\n=== 2) 마모율 (랩당 손실) ===")
    for c in COMPOUNDS:
        rates = [deg_rate(c, tl, 20) for tl in [5, 15, 25]]
        print(f"  {c:<7} life5={rates[0]:+.3f}s  "
              f"life15={rates[1]:+.3f}s  life25={rates[2]:+.3f}s /lap")

    print("\n=== 3) 피트 윈도우 시뮬레이션 ===")
    print("  시나리오: 25랩째, HARD 20랩 사용. 지금 vs 5랩 더 끌기")
    # 지금 피트: 새 MEDIUM 으로 남은 10랩
    now_pit = stint_cost("MEDIUM", 0, 25, 10)
    # 5랩 더 끌고 피트: 늙은 HARD 5랩 + 새 MEDIUM 5랩
    late_pit = stint_cost("HARD", 20, 25, 5) + stint_cost("MEDIUM", 0, 30, 5)
    print(f"  지금 피트 (MEDIUM 10랩):        {now_pit:.1f}s")
    print(f"  5랩 더 끌고 피트 (HARD5+MED5):  {late_pit:.1f}s")
    diff = late_pit - now_pit
    print(f"  → {'지금 피트가' if diff > 0 else '늦게 피트가'} "
          f"{abs(diff):.1f}s 유리 (피트스톱 ~22s 손실은 별도 고려)")


if __name__ == "__main__":
    main()
