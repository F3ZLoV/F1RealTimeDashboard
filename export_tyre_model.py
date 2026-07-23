"""
tyre_model.pt (PyTorch) → tyre_model.json (JS 추론용) 내보내기.

train_tyre_model 을 import 하지 않고 모델 구조를 여기서 직접 정의한다
(numpy/pandas/sklearn 의존 제거 — torch 만 있으면 됨).

실행:
  cd E:\\F1RealTimeDashboard
  python export_tyre_model.py

출력:
  tyre_model.json  → f1-hub/src/lib/tyre_model.json 으로 복사
"""
import json

import torch
import torch.nn as nn

SCALER = "scaler.json"
WEIGHTS = "tyre_model.pt"
OUT = "tyre_model.json"


class TyreModel(nn.Module):
    """train_tyre_model.py 와 동일한 구조 (가중치 로드용)."""
    def __init__(self, in_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 32), nn.ReLU(),
            nn.Linear(32, 16), nn.ReLU(),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        return self.net(x)


def main():
    with open(SCALER, encoding="utf-8") as f:
        sc = json.load(f)
    compounds = sc["compounds"]

    model = TyreModel(len(compounds) + 2)
    model.load_state_dict(torch.load(WEIGHTS, map_location="cpu"))
    model.eval()

    sd = model.state_dict()
    # nn.Sequential 인덱스: 0=Linear(in,32), 2=Linear(32,16), 4=Linear(16,1)
    layers = []
    for idx in (0, 2, 4):
        layers.append({
            "w": sd[f"net.{idx}.weight"].tolist(),   # [out][in]
            "b": sd[f"net.{idx}.bias"].tolist(),     # [out]
        })

    payload = {
        "compounds": compounds,   # 원-핫 순서 (학습과 동일해야 함)
        "mean": sc["mean"],       # [tyre_life, lap_number]
        "std": sc["std"],
        "layers": layers,         # relu 는 마지막 층 제외하고 적용
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    print(f"{OUT} 저장 — 레이어 출력차원 {[len(l['b']) for l in layers]}")
    print("\n검증용 샘플 (JS 결과와 일치해야 함):")
    for comp in compounds:
        oh = [1.0 if comp == c else 0.0 for c in compounds]
        for life in (0, 10, 20):
            num = [
                (life - sc["mean"][0]) / sc["std"][0],
                (15 - sc["mean"][1]) / sc["std"][1],
            ]
            x = torch.tensor([oh + num], dtype=torch.float32)
            with torch.no_grad():
                y = model(x).item()
            print(f"  {comp:<7} life={life:>2} lap=15 → {y:.4f}s")


if __name__ == "__main__":
    main()
    