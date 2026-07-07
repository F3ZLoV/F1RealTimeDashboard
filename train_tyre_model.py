"""
타이어 마모 예측 모델 학습 (PyTorch).

모델: f(compound, tyre_life, lap_number) -> lap_duration (절대 랩타임)
  - 절대 랩타임 = 대시보드 표시용
  - 같은 모델에 tyre_life 를 1씩 굴리면 그 차이가 곧 '마모율' (predict_strategy.py)

SageMaker 이식성:
  이 스크립트 구조(데이터로드 → 전처리 → 학습 → 저장)는 SageMaker 학습 잡과 동일.
  계정 오면 데이터 경로(S3)와 모델 저장 경로만 환경변수로 바꾸면 거의 그대로 올라감.

출력:
  tyre_model.pt        학습된 모델 가중치
  scaler.json          입력 정규화 파라미터 (추론 시 동일 적용 필요)
  tyre_curve.png       검증: tyre_life vs 예측 랩타임 곡선
"""
import json

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.model_selection import train_test_split

DATA = "ml_dataset.csv"
COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]   # 원-핫 순서 고정
EPOCHS = 400
LR = 0.01
SEED = 42

torch.manual_seed(SEED)
np.random.seed(SEED)


# ── 전처리 ──────────────────────────────────────────────
def featurize(df):
    """compound(원-핫) + tyre_life + lap_number -> X, lap_duration -> y"""
    onehot = np.zeros((len(df), len(COMPOUNDS)), dtype=np.float32)
    for i, c in enumerate(df["compound"]):
        if c in COMPOUNDS:
            onehot[i, COMPOUNDS.index(c)] = 1.0
    num = df[["tyre_life", "lap_number"]].to_numpy(dtype=np.float32)
    X = np.hstack([onehot, num])
    y = df["lap_duration"].to_numpy(dtype=np.float32).reshape(-1, 1)
    return X, y


# ── 모델 ────────────────────────────────────────────────
class TyreModel(nn.Module):
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
    df = pd.read_csv(DATA)
    print(f"데이터 {len(df)}행 로드")

    X, y = featurize(df)
    # 수치 피처(tyre_life, lap_number)만 표준화. 원-핫은 그대로.
    num_cols = slice(len(COMPOUNDS), None)
    mean = X[:, num_cols].mean(axis=0)
    std = X[:, num_cols].std(axis=0) + 1e-8
    X[:, num_cols] = (X[:, num_cols] - mean) / std

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=SEED)
    Xtr, Xte = torch.tensor(Xtr), torch.tensor(Xte)
    ytr, yte = torch.tensor(ytr), torch.tensor(yte)

    model = TyreModel(X.shape[1])
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    lossfn = nn.MSELoss()

    for ep in range(EPOCHS):
        model.train()
        opt.zero_grad()
        loss = lossfn(model(Xtr), ytr)
        loss.backward()
        opt.step()
        if (ep + 1) % 50 == 0:
            model.eval()
            with torch.no_grad():
                te = lossfn(model(Xte), yte).item()
            print(f"epoch {ep+1:>3}  train {loss.item():.3f}  test {te:.3f}")

    # 검증 지표 (RMSE, 초 단위)
    model.eval()
    with torch.no_grad():
        pred = model(Xte)
        rmse = torch.sqrt(lossfn(pred, yte)).item()
    print(f"\n테스트 RMSE: {rmse:.3f}초 "
          f"(랩타임 예측이 평균 ±{rmse:.2f}초 오차)")

    # 저장
    torch.save(model.state_dict(), "tyre_model.pt")
    with open("scaler.json", "w") as f:
        json.dump({"mean": mean.tolist(), "std": std.tolist(),
                   "compounds": COMPOUNDS}, f)
    print("tyre_model.pt / scaler.json 저장")

    plot_curve(model, mean, std)


def plot_curve(model, mean, std):
    """검증: 각 컴파운드별 tyre_life ↑ 에 따른 예측 랩타임 곡선.
    물리적으로 맞다면 우상향(늙을수록 느려짐)이어야 함."""
    import matplotlib.pyplot as plt
    plt.figure(figsize=(9, 6))
    lives = np.arange(0, 40)
    for c in COMPOUNDS:
        feats = []
        for tl in lives:
            oh = [1.0 if c == cc else 0.0 for cc in COMPOUNDS]
            num = [(tl - mean[0]) / std[0], (15 - mean[1]) / std[1]]  # lap 15 고정
            feats.append(oh + num)
        with torch.no_grad():
            pred = model(torch.tensor(feats, dtype=torch.float32)).numpy().flatten()
        plt.plot(lives, pred, label=c, linewidth=2)
    plt.xlabel("Tyre life (laps)")
    plt.ylabel("Predicted lap time (s)")
    plt.title("Tyre degradation curve (up = learned correctly)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig("tyre_curve.png", dpi=120, bbox_inches="tight")
    print("tyre_curve.png 저장 — 곡선이 우상향인지 확인")


if __name__ == "__main__":
    main()
