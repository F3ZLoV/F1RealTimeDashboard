"""
텔레메트리 파싱 & 정규화 모듈.

실데이터에서 확인된 규칙을 코드로 고정:
  - 차고 정지 노이즈(speed=0 & x=0 등) 필터링
  - car_data / location 을 DynamoDB/KDS 공통 레코드 형태로 변환
  - PK/SK 키 생성 (확정된 키 모델)

이 모듈은 과거 데이터(REST)와 실시간(MQTT) 양쪽에서 공통으로 씀.
"""
from typing import Optional


def make_pk(session_key, driver_number) -> str:
    return f"{session_key}#{driver_number}"


def make_sk(record_type: str, date: str) -> str:
    return f"{record_type}#{date}"


def is_garage_noise_car(rec: dict) -> bool:
    """차고 정지 car_data: 속도/RPM/스로틀이 전부 0이면 노이즈로 간주."""
    return (rec.get("speed", 0) == 0
            and rec.get("rpm", 0) == 0
            and rec.get("throttle", 0) == 0)


def is_garage_noise_loc(rec: dict) -> bool:
    """차고 정지 location: 좌표가 0,0 이면 노이즈."""
    return rec.get("x", 0) == 0 and rec.get("y", 0) == 0


def normalize_car(rec: dict) -> Optional[dict]:
    """car_data 한 건 → 공통 레코드. 노이즈면 None."""
    if is_garage_noise_car(rec):
        return None
    date = rec.get("date")
    if not date:
        return None
    return {
        "pk": make_pk(rec["session_key"], rec["driver_number"]),
        "sk": make_sk("car", date),
        "type": "car",
        "session_key": rec["session_key"],
        "driver_number": rec["driver_number"],
        "date": date,
        "speed": rec.get("speed"),
        "throttle": rec.get("throttle"),
        "brake": rec.get("brake"),
        "n_gear": rec.get("n_gear"),
        "rpm": rec.get("rpm"),
        "drs": rec.get("drs"),
    }


def normalize_loc(rec: dict) -> Optional[dict]:
    """location 한 건 → 공통 레코드. 노이즈면 None."""
    if is_garage_noise_loc(rec):
        return None
    date = rec.get("date")
    if not date:
        return None
    return {
        "pk": make_pk(rec["session_key"], rec["driver_number"]),
        "sk": make_sk("loc", date),
        "type": "loc",
        "session_key": rec["session_key"],
        "driver_number": rec["driver_number"],
        "date": date,
        "x": rec.get("x"),
        "y": rec.get("y"),
        "z": rec.get("z"),
    }


def normalize_batch(records: list, kind: str):
    """레코드 리스트를 정규화. kind = 'car' | 'loc'. 노이즈는 제거."""
    fn = normalize_car if kind == "car" else normalize_loc
    out = []
    dropped = 0
    for r in records:
        n = fn(r)
        if n is None:
            dropped += 1
        else:
            out.append(n)
    return out, dropped
