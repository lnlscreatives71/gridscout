"""Runs a grid scan: one local-pack query per pin, find the target, score it."""
import difflib
import sys
from concurrent.futures import ThreadPoolExecutor

from .grid import build_grid
from .providers import get_provider

NOT_FOUND = None


def _match(target: str, name: str) -> bool:
    t, n = target.lower().strip(), (name or "").lower().strip()
    if t in n or n in t:
        return True
    return difflib.SequenceMatcher(None, t, n).ratio() >= 0.85


def run_scan(business: str, keyword: str, center_lat: float, center_lng: float,
             size: int = 7, radius_miles: float = 3.0, depth: int = 20,
             provider_name: str | None = None, workers: int = 8):
    provider = get_provider(provider_name)
    points = build_grid(center_lat, center_lng, size, radius_miles)

    def one(p):
        results = provider.search(keyword, p["lat"], p["lng"], depth)
        rank = NOT_FOUND
        for r in results:
            if _match(business, r["name"]):
                rank = r["rank"]
                break
        return {**p, "rank": rank, "results": results}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        pins = list(ex.map(one, points))

    pins.sort(key=lambda p: (p["row"], p["col"]))

    found = [p["rank"] for p in pins if p["rank"] is not None]
    n = len(pins)
    avg_rank = round(sum(found) / len(found), 2) if found else None
    top3 = sum(1 for r in found if r <= 3)
    # Visibility: 100 at rank 1, 0 if not found. Linear falloff across depth.
    vis = round(
        sum(max(0.0, (depth - (r - 1)) / depth) for r in found) / n * 100, 1
    ) if n else 0.0

    meta = {
        "business": business,
        "keyword": keyword,
        "center_lat": center_lat,
        "center_lng": center_lng,
        "grid_size": size,
        "radius_miles": radius_miles,
        "provider": provider.name,
        "avg_rank": avg_rank,
        "visibility": vis,
        "top3_pct": round(top3 / n * 100, 1),
        "found_pct": round(len(found) / n * 100, 1),
    }
    return meta, pins


def print_summary(meta, pins, out=sys.stdout):
    size = meta["grid_size"]
    print(f"\n  {meta['business']}  |  \"{meta['keyword']}\"", file=out)
    print(f"  {size}x{size} grid, {meta['radius_miles']} mi radius, "
          f"provider={meta['provider']}\n", file=out)
    grid = {(p["row"], p["col"]): p["rank"] for p in pins}
    for r in range(size):
        row = "   "
        for c in range(size):
            v = grid[(r, c)]
            row += f"{'  X' if v is None else f'{v:3d}'} "
        print(row, file=out)
    print(f"\n  Avg rank (where found): {meta['avg_rank']}", file=out)
    print(f"  Visibility score:       {meta['visibility']}", file=out)
    print(f"  Pins in top 3:          {meta['top3_pct']}%", file=out)
    print(f"  Pins where found:       {meta['found_pct']}%   (X = not in top "
          f"{20})\n", file=out)
