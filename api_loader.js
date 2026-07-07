/*
 * api_loader.js — 대시보드 데이터 소스를 임베드 JS → API fetch 로 교체하는 자리.
 *
 * 로컬 프로토타입: <script src="replay_full.js"> 로 window.REPLAY 를 통째로 임베드
 * AWS 배포:        이 로더가 API Gateway(query Lambda)를 호출해 같은 형태로 구성
 *
 * 사용법 (dashboard_full.html 에서):
 *   1) <script src="replay_full.js"></script>  ← 이 줄을 아래로 교체
 *      <script src="api_loader.js"></script>
 *   2) 그 다음 인라인 <script> 의 첫 줄
 *        const data = window.REPLAY;
 *      를
 *        const data = await loadReplay();   // (스크립트를 async IIFE 로 감싸기)
 *      로 바꾼다.
 *
 * API_ENDPOINT 는 terraform output 의 api_endpoint 값으로 채운다.
 */

const API_ENDPOINT = "https://<API_ID>.execute-api.us-east-1.amazonaws.com/telemetry";
const SESSION_KEY = 9165;
const DRIVERS = [1, 2, 4, 10, 11, 14, 16, 20, 22, 23, 24, 27, 31, 40, 44, 55, 63, 77, 81];

async function fetchType(driver, type) {
  const url = `${API_ENDPOINT}?session=${SESSION_KEY}&driver=${driver}&type=${type}&limit=2000`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API ${res.status} for #${driver} ${type}`);
  return res.json();
}

// car/loc 를 시간축으로 병합 → 대시보드 프레임 형태로 (build_replay 와 동일 로직)
function mergeFrames(car, loc) {
  car.sort((a, b) => a.date.localeCompare(b.date));
  loc.sort((a, b) => a.date.localeCompare(b.date));
  const carTs = car.map(c => Date.parse(c.date));
  const nearest = (t) => {
    // 이진탐색 대신 단순 근접(데이터 적당량 가정)
    let lo = 0, hi = carTs.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (carTs[mid] < t) lo = mid + 1; else hi = mid;
    }
    return car[Math.max(0, lo - (carTs[lo] > t ? 1 : 0))] || car[0];
  };
  if (!loc.length) return [];
  const t0 = Date.parse(loc[0].date);
  return loc.map(p => {
    const c = nearest(Date.parse(p.date));
    return {
      t: (Date.parse(p.date) - t0) / 1000,
      x: p.x, y: p.y,
      speed: c?.speed, gear: c?.n_gear,
      throttle: c?.throttle, brake: c?.brake, drs: c?.drs,
    };
  });
}

// 대시보드가 기대하는 window.REPLAY 형태로 구성
async function loadReplay() {
  const drivers = [];
  const allX = [], allY = [];
  for (const drv of DRIVERS) {
    try {
      const [car, loc] = await Promise.all([
        fetchType(drv, "car"),
        fetchType(drv, "loc"),
      ]);
      const frames = mergeFrames(car, loc);
      if (!frames.length) continue;
      drivers.push({ number: drv, acronym: String(drv), frames });
      frames.forEach(f => { allX.push(f.x); allY.push(f.y); });
    } catch (e) {
      console.warn(e);
    }
  }
  return {
    session_key: SESSION_KEY,
    drivers,
    bounds: {
      minX: Math.min(...allX), maxX: Math.max(...allX),
      minY: Math.min(...allY), maxY: Math.max(...allY),
    },
  };
}
