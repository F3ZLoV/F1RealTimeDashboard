import json

with open("replay_full.js", encoding="utf-8") as f:
    txt = f.read()
data = json.loads(txt[len("window.REPLAY = "):-1])

for d in data["drivers"][:3]:
    fr = d["frames"]
    ts = [f["t"] for f in fr]
    laps = [f["lap"] for f in fr]
    print(f"#{d['number']} {d['acronym']}: "
          f"{len(fr)}프레임, t범위 {min(ts):.0f}~{max(ts):.0f}초, "
          f"랩 {min(laps)}~{max(laps)}")