"""
리플레이 청크 빌더 Lambda — build_replay_full.py 의 서버리스 이식.

  API Gateway (GET /replay?session_key=&start=&dur=&hz=)
    → S3 캐시 확인 (있으면 즉시 반환)
    → 없으면 OpenF1 에서 좌표/텔레메트리 수집
       → 노이즈 필터 → 시간축 근접조인 → 랩/컴파운드 매핑 → 다운샘플링
       → 컬럼형 JSON 생성 → S3 저장 → 반환

설계 메모:
  - 외부 패키지 없음 (urllib + boto3(런타임 내장)) → Lambda 레이어 불필요
  - 응답은 gzip + base64 (Lambda 응답 6MB 제한 회피, 전송량 1/6)
  - 캐시 실패(권한 등)는 치명적이지 않게 처리 — 캐시 없이도 동작
  - 타이어 마모 예측은 tyre_model.json 가중치로 순수 파이썬 forward pass

필요 권한 (Lambda 실행 Role):
  s3:GetObject, s3:PutObject  (캐시 버킷)
"""
import base64
import gzip
import json
import os
import urllib.parse
import urllib.request
from bisect import bisect_left

import boto3

OPENF1 = "https://api.openf1.org/v1"
CACHE_BUCKET = os.environ.get("CACHE_BUCKET", "")
CACHE_PREFIX = os.environ.get("CACHE_PREFIX", "replay-cache")
COMPOUND_CODES = ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"]

s3 = boto3.client("s3") if CACHE_BUCKET else None

# ── 타이어 마모 모델 (PyTorch 가중치 → 순수 파이썬 추론) ──
_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        path = os.path.join(os.path.dirname(__file__), "tyre_model.json")
        try:
            with open(path, encoding="utf-8") as f:
                _MODEL = json.load(f)
        except Exception:
            _MODEL = {}
    return _MODEL


def _linear(x, w, b):
    return [sum(wi * xi for wi, xi in zip(row, x)) + bi for row, bi in zip(w, b)]


def predict_lap_time(compound, tyre_life, lap_number=15):
    m = _model()
    if not m or compound not in m.get("compounds", []):
        return None
    comps = m["compounds"]
    mean, std = m["mean"], m["std"]
    x = [1.0 if c == compound else 0.0 for c in comps]
    x += [(tyre_life - mean[0]) / std[0], (lap_number - mean[1]) / std[1]]
    layers = m["layers"]
    for i, layer in enumerate(layers):
        x = _linear(x, layer["w"], layer["b"])
        if i < len(layers) - 1:            # 마지막 층은 활성함수 없음
            x = [v if v > 0 else 0.0 for v in x]
    return x[0]


def degradation_curve(compound, max_age=35):
    if not compound:
        return None
    curve = []
    for age in range(max_age + 1):
        v = predict_lap_time(compound, age)
        curve.append(None if v is None else round(v, 2))
    return curve if any(v is not None for v in curve) else None


# ── OpenF1 호출 ──────────────────────────────────────
def of1(path, params):
    qs = urllib.parse.urlencode(params)
    url = f"{OPENF1}/{path}?{qs}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def ts(date_str):
    """ISO 문자열 → epoch ms. OpenF1은 오프셋 유무가 섞여 있어 정규화."""
    d = date_str.replace("Z", "+00:00")
    if "+" not in d[10:] and "-" not in d[10:]:
        d += "+00:00"
    from datetime import datetime
    return int(datetime.fromisoformat(d).timestamp() * 1000)


# ── 응답 헬퍼 ────────────────────────────────────────
def respond(payload, status=200, gzip_body=True):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=604800",
    }
    if gzip_body and len(body) > 1024:
        packed = gzip.compress(body.encode("utf-8"), 6)
        headers["Content-Encoding"] = "gzip"
        return {
            "statusCode": status,
            "headers": headers,
            "body": base64.b64encode(packed).decode("ascii"),
            "isBase64Encoded": True,
        }
    return {"statusCode": status, "headers": headers, "body": body}


def error(msg, status=400):
    return respond({"error": msg}, status, gzip_body=False)


# ── 캐시 ─────────────────────────────────────────────
def cache_key(session_key, start, dur, hz):
    return f"{CACHE_PREFIX}/{session_key}/{start}_{dur}_{hz}.json.gz"


def cache_get(key):
    if not s3:
        return None
    try:
        obj = s3.get_object(Bucket=CACHE_BUCKET, Key=key)
        return json.loads(gzip.decompress(obj["Body"].read()).decode("utf-8"))
    except Exception:
        return None


def cache_put(key, payload):
    if not s3:
        return
    try:
        packed = gzip.compress(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6
        )
        s3.put_object(Bucket=CACHE_BUCKET, Key=key, Body=packed,
                      ContentType="application/json", ContentEncoding="gzip")
    except Exception as e:
        print(f"[cache] 저장 실패(무시): {e}")



def sector_points(laps, loc_by, t0):
    """
    섹터 경계 좌표 — 랩의 섹터별 소요시간을 절대 시각으로 환산한 뒤
    그 순간 차량이 어디 있었는지 찾는다. (S1→S2, S2→S3 두 지점)

    어느 API도 섹터 분할 지점의 좌표를 주지 않지만,
    laps 의 duration_sector_1/2 와 date_start 로 정확히 역산할 수 있다.
    """
    # 좌표가 가장 촘촘한 드라이버를 기준으로
    if not loc_by:
        return []
    ref = max(loc_by.items(), key=lambda kv: len(kv[1]))
    num, points = ref
    pts = sorted(points, key=lambda r: r["date"])
    p_ts = [ts(r["date"]) for r in pts]

    def at(t):
        i = bisect_left(p_ts, t)
        if i <= 0:
            return None
        if i >= len(pts):
            return None
        a, b = pts[i - 1], pts[i]
        return a if abs(p_ts[i - 1] - t) <= abs(p_ts[i] - t) else b

    for lp in laps:
        if lp.get("driver_number") != num or not lp.get("date_start"):
            continue
        s1, s2 = lp.get("duration_sector_1"), lp.get("duration_sector_2")
        if not s1 or not s2:
            continue
        start = ts(lp["date_start"])
        p1 = at(start + int(s1 * 1000))
        p2 = at(start + int((s1 + s2) * 1000))
        if p1 and p2:
            return [
                {"n": 2, "x": p1["x"], "y": p1["y"]},
                {"n": 3, "x": p2["x"], "y": p2["y"]},
            ]
    return []


# ── 빌드 ─────────────────────────────────────────────
def build(session_key, start_off, dur, hz):
    sessions = of1("sessions", {"session_key": session_key})
    if not sessions:
        return None, "세션을 찾을 수 없음"
    session = sessions[0]

    drivers = of1("drivers", {"session_key": session_key})
    laps = of1("laps", {"session_key": session_key})
    stints = of1("stints", {"session_key": session_key})

    lap_starts = [
        {"n": l["lap_number"], "d": l["driver_number"], "t": ts(l["date_start"])}
        for l in laps if l.get("date_start")
    ]
    firsts = [l["t"] for l in lap_starts if l["n"] == 1]
    t0 = min(firsts) if firsts else ts(session["date_start"])

    end_t = ts(session["date_end"]) if session.get("date_end") else None
    last_lap = max([l["t"] for l in lap_starts], default=t0)
    total_dur = max(60, round(((end_t if end_t else last_lap + 180_000) - t0) / 1000))

    from datetime import datetime, timezone
    iso = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "")
    frm = iso(t0 + start_off * 1000)
    to = iso(t0 + (start_off + dur) * 1000)

    loc = of1("location", {"session_key": session_key, "date>": frm, "date<": to})
    car = of1("car_data", {"session_key": session_key, "date>": frm, "date<": to})

    # 드라이버별 그룹 + 노이즈 제거
    loc_by, car_by = {}, {}
    for r in loc:
        if not r.get("x") and not r.get("y"):
            continue
        loc_by.setdefault(r["driver_number"], []).append(r)
    for r in car:
        if not r.get("speed") and not r.get("rpm") and not r.get("throttle"):
            continue
        car_by.setdefault(r["driver_number"], []).append(r)

    stint_by, lap_by = {}, {}
    for s in stints:
        stint_by.setdefault(s["driver_number"], []).append(s)
    for l in lap_starts:
        lap_by.setdefault(l["d"], []).append(l)
    meta_by = {d["driver_number"]: d for d in drivers}

    gap_ms = 1000.0 / hz
    out = []
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    for num, points in loc_by.items():
        points.sort(key=lambda r: r["date"])
        cars = sorted(car_by.get(num, []), key=lambda r: r["date"])
        car_ts = [ts(c["date"]) for c in cars]
        my_laps = sorted(lap_by.get(num, []), key=lambda l: l["t"])
        my_stints = stint_by.get(num, [])

        def nearest(t):
            if not cars:
                return None
            i = bisect_left(car_ts, t)
            if i == 0:
                return cars[0]
            if i >= len(cars):
                return cars[-1]
            return cars[i - 1] if abs(car_ts[i - 1] - t) <= abs(car_ts[i] - t) else cars[i]

        def lap_at(t):
            n = 0
            for l in my_laps:
                if t >= l["t"]:
                    n = l["n"]
                else:
                    break
            return n if n > 0 else 1

        def stint_at(lap_no):
            for st in my_stints:
                ls = st.get("lap_start")
                if ls is None:
                    continue
                le = st.get("lap_end") or ls + 99
                if ls <= lap_no <= le:
                    return st.get("compound"), (st.get("tyre_age_at_start") or 0) + (lap_no - ls)
            return None, None

        T, X, Y = [], [], []
        SP, GR, TH, BR, DR, LP, CP, AG = [], [], [], [], [], [], [], []
        last_emit = float("-inf")
        last_comp = None

        for p in points:
            t = ts(p["date"])
            if t - last_emit < gap_ms:
                continue
            last_emit = t
            c = nearest(t) or {}
            lap_no = lap_at(t)
            comp, age = stint_at(lap_no)
            if comp:
                last_comp = comp

            T.append(round((t - t0) / 1000.0, 2))
            X.append(p["x"]); Y.append(p["y"])
            SP.append(c.get("speed")); GR.append(c.get("n_gear"))
            TH.append(c.get("throttle")); BR.append(c.get("brake"))
            DR.append(c.get("drs")); LP.append(lap_no)
            CP.append(COMPOUND_CODES.index(comp) if comp in COMPOUND_CODES else -1)
            AG.append(age)

            min_x = min(min_x, p["x"]); max_x = max(max_x, p["x"])
            min_y = min(min_y, p["y"]); max_y = max(max_y, p["y"])

        if len(T) < 5:
            continue
        m = meta_by.get(num, {})
        out.append({
            "number": num,
            "acronym": m.get("name_acronym") or str(num),
            "name": m.get("full_name", ""),
            "team": m.get("team_name", ""),
            "colour": "#" + (m.get("team_colour") or "888888"),
            "t": T, "x": X, "y": Y,
            "speed": SP, "gear": GR, "throttle": TH, "brake": BR, "drs": DR,
            "lap": LP, "comp": CP, "age": AG,
            "deg_curve": degradation_curve(last_comp),
        })

    out.sort(key=lambda d: d["number"])

    payload = {
        "session_key": int(session_key),
        "year": session.get("year"),
        "session_name": session.get("session_name"),
        "circuit": session.get("circuit_short_name"),
        "country": session.get("country_name"),
        "compounds": COMPOUND_CODES,
        "chunk": {"start": start_off, "dur": dur, "hz": hz},
        "total_dur": total_dur,
        "drivers": out,
        "sectors": sector_points(laps, loc_by, t0),
        "bounds": ({"minX": min_x, "maxX": max_x, "minY": min_y, "maxY": max_y}
                   if out else None),
    }
    return payload, None


# ── 핸들러 ───────────────────────────────────────────
def lambda_handler(event, context):
    qs = event.get("queryStringParameters") or {}
    session_key = qs.get("session_key")
    if not session_key:
        return error("session_key 필요")

    try:
        start_off = max(0, int(float(qs.get("start", 0))))
        dur = min(max(int(float(qs.get("dur", 300))), 30), 600)
        hz = min(max(float(qs.get("hz", 2)), 0.5), 4)
    except ValueError:
        return error("파라미터 형식 오류")

    key = cache_key(session_key, start_off, dur, hz)
    cached = cache_get(key)
    if cached:
        print(f"[cache] HIT {key}")
        return respond(cached)

    print(f"[cache] MISS {key} — OpenF1 에서 빌드")
    try:
        payload, err = build(session_key, start_off, dur, hz)
    except Exception as e:
        print(f"[build] 실패: {e}")
        return error(f"리플레이 빌드 실패: {e}", 502)
    if err:
        return error(err, 404)

    cache_put(key, payload)
    return respond(payload)
