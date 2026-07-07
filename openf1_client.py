"""
OpenF1 API 클라이언트 — 과거(무료) 데이터 탐색용.
Base URL: https://api.openf1.org/v1
실시간/인증 없이 2023년 이후 데이터에 접근 가능.
"""
import time
import requests

BASE_URL = "https://api.openf1.org/v1"


class OpenF1:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()

    def get(self, endpoint: str, max_retries: int = 4, **params):
        """
        엔드포인트 GET 호출. 필터는 키워드로 전달.
        예: client.get("car_data", session_key=9161, driver_number=81)
        OpenF1은 관계연산자 필터를 지원: date=">2023-09-16T13:03:35.200"
        """
        url = f"{BASE_URL}/{endpoint.lstrip('/')}"
        for attempt in range(max_retries + 1):
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code == 429 and attempt < max_retries:
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s
                print(f"  [rate limit] {wait}s 대기 후 재시도...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()

    # --- 편의 메서드 ---
    def sessions(self, **params):
        return self.get("sessions", **params)

    def drivers(self, **params):
        return self.get("drivers", **params)

    def car_data(self, **params):
        return self.get("car_data", **params)

    def location(self, **params):
        return self.get("location", **params)

    def laps(self, **params):
        return self.get("laps", **params)

    def stints(self, **params):
        return self.get("stints", **params)
