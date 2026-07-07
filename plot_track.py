"""
트랙맵 시각화 — location 데이터로 실제 서킷 모양이 나오는지 확인.
explore.py 를 먼저 돌려서 samples/location.json 이 있어도 되고,
이 스크립트가 직접 API를 호출해도 됨.

사용:
  python plot_track.py
  → track_map.png 생성
"""
import matplotlib.pyplot as plt

from openf1_client import OpenF1

SESSION_KEY = 9165      # 2023 Singapore GP - Race
DRIVER_NUMBER = 1       # Max Verstappen

client = OpenF1()


def main():
    print("location 데이터 가져오는 중...")
    data = client.location(session_key=SESSION_KEY, driver_number=DRIVER_NUMBER)
    pts = [(p["x"], p["y"]) for p in data
           if p.get("x") is not None and p.get("y") is not None
           and not (p["x"] == 0 and p["y"] == 0)]  # 0,0 노이즈 제거
    print(f"좌표 {len(pts):,}개")

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    plt.figure(figsize=(10, 10))
    plt.scatter(xs, ys, s=1, alpha=0.3)
    plt.title(f"Track map — session {SESSION_KEY}, driver #{DRIVER_NUMBER}")
    plt.axis("equal")
    plt.grid(True, alpha=0.2)
    plt.savefig("track_map.png", dpi=120, bbox_inches="tight")
    print("track_map.png 저장됨 — 열어서 서킷 모양 확인해봐.")


if __name__ == "__main__":
    main()
