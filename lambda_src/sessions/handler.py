"""
세션 목록 Lambda — 리플레이 선택 UI용.

  GET /sessions?year=2024        → 그 시즌 그랑프리(meetings) 목록 (~24행)
  GET /sessions?meeting_key=1234 → 해당 그랑프리의 세션 목록 (~5행)

두 단계로 나눈 이유: 한 번에 시즌 전체 세션을 받으면 응답이 커지고,
프리시즌 테스팅까지 섞여 UI가 지저분해진다. GP → 세션 순으로 좁힌다.

외부 패키지 없음 (urllib). OpenF1 호출을 그대로 프록시하며 CORS 헤더만 붙인다.
"""
import json
import urllib.parse
import urllib.request

OPENF1 = "https://api.openf1.org/v1"
FIRST_YEAR = 2023  # OpenF1 제공 시작


def of1(path, params):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{OPENF1}/{path}?{qs}", headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def respond(payload, status=200):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=86400",
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }


def lambda_handler(event, context):
    qs = event.get("queryStringParameters") or {}
    meeting_key = qs.get("meeting_key")
    year = qs.get("year")

    try:
        # ── 세션 목록 (특정 그랑프리) ──
        if meeting_key:
            raw = of1("sessions", {"meeting_key": meeting_key})
            sessions = sorted(
                [s for s in raw if s.get("session_key") and s.get("date_start")],
                key=lambda s: s["date_start"],          # 주말 진행 순서
            )
            return respond({"sessions": sessions})

        # ── 그랑프리 목록 (연도) ──
        y = int(year or 0)
        if y < FIRST_YEAR:
            return respond(
                {"error": f"OpenF1은 {FIRST_YEAR}년부터 데이터를 제공합니다."}, 400
            )
        raw = of1("meetings", {"year": y})
        meetings = [
            m for m in raw
            if m.get("meeting_key") and m.get("date_start")
            # 프리시즌 테스팅은 그랑프리가 아니므로 제외
            and "testing" not in (m.get("meeting_name") or "").lower()
            and "testing" not in (m.get("meeting_official_name") or "").lower()
        ]
        meetings.sort(key=lambda m: m["date_start"], reverse=True)  # 최신 GP 위로
        return respond({"year": y, "meetings": meetings})

    except ValueError:
        return respond({"error": "year 형식 오류"}, 400)
    except Exception as e:
        print(f"[sessions] 실패: {e}")
        return respond({"error": f"조회 실패: {e}"}, 502)
