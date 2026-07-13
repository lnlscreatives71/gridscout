"""Mock provider. Simulates a real local pack so the whole pipeline runs with no key.

Models the thing that actually drives Maps rank: proximity, with prominence as a
tiebreaker. Each fake business has a home lat/lng and a prominence score; rank at
a given pin is derived from distance-penalized prominence, plus a little noise.
"""
import hashlib
import math
import random

# A fake competitive set. business at index 0 is treated as "the client" by
# convention only; the scanner matches by name, not by position.
FAKE_SET = [
    # name, lat_offset_miles, lng_offset_miles, prominence, category
    ("Summit Air & Heating", 0.0, 0.0, 62, "HVAC contractor"),
    ("Buckeye Comfort Systems", 1.8, -2.1, 88, "HVAC contractor"),
    ("Ridgeline Heating and Cooling", -2.4, 1.6, 81, "HVAC contractor"),
    ("Capital City Air", 3.1, 2.8, 74, "HVAC contractor"),
    ("Northside Mechanical", -3.3, -2.9, 70, "HVAC contractor"),
    ("Trueline HVAC Co.", 0.9, 3.4, 66, "HVAC contractor"),
    ("AllSeason Air Solutions", -1.2, -3.6, 59, "HVAC contractor"),
    ("Meridian Heating Services", 2.6, -3.2, 55, "HVAC contractor"),
    ("Old Town Furnace & Air", -3.8, 0.4, 51, "Heating contractor"),
    ("Prime Climate Control", 4.0, -1.1, 47, "HVAC contractor"),
    ("Halcyon Air Systems", -0.6, 4.2, 44, "HVAC contractor"),
    ("Ironwood Heating", 3.7, 3.9, 40, "HVAC contractor"),
]


class MockProvider:
    name = "mock"

    def __init__(self, seed: int = 7):
        self.seed = seed

    def search(self, keyword: str, lat: float, lng: float, depth: int = 20):
        # deterministic per-pin noise
        h = hashlib.md5(f"{keyword}{lat}{lng}{self.seed}".encode()).hexdigest()
        rng = random.Random(int(h[:8], 16))

        lat_per_mile = 1.0 / 69.0
        lng_per_mile = 1.0 / (69.0 * math.cos(math.radians(lat)))

        scored = []
        for name, dy, dx, prom, cat in FAKE_SET:
            # business home position is defined relative to the FIRST pin's frame;
            # we anchor it to a fixed origin so it stays put across the grid.
            b_lat = 39.9612 + dy * lat_per_mile
            b_lng = -82.9988 + dx * lng_per_mile
            d = math.hypot((lat - b_lat) / lat_per_mile, (lng - b_lng) / lng_per_mile)
            # proximity dominates, prominence modulates
            score = prom - (d ** 1.35) * 9.0 + rng.uniform(-4, 4)
            scored.append((score, name, prom, cat, d))

        scored.sort(reverse=True, key=lambda t: t[0])
        out = []
        for i, (score, name, prom, cat, d) in enumerate(scored[:depth], start=1):
            out.append({
                "rank": i,
                "name": name,
                "place_id": "mock_" + hashlib.md5(name.encode()).hexdigest()[:12],
                "rating": round(3.6 + prom / 100.0 * 1.3, 1),
                "reviews": int(prom * 4.2),
                "category": cat,
            })
        return out
