from collections import Counter
from openf1_client import OpenF1

c = OpenF1()
car = c.get("car_data", session_key=9165, driver_number=1)

counts = Counter(r["drs"] for r in car)
print("DRS 값 분포:", dict(sorted(counts.items())))

# DRS ON(10/12/14) 비율
on = sum(counts.get(v, 0) for v in [10, 12, 14])
print(f"DRS ON 레코드: {on:,} / 전체 {len(car):,} ({on/len(car)*100:.1f}%)")