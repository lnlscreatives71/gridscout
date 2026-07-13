"""gridscout CLI.

  gridscout scan --business "Summit Air & Heating" --keyword "hvac repair" \
      --lat 39.9612 --lng -82.9988 --size 7 --radius 3 --provider mock

  gridscout history --business "Summit Air & Heating" --keyword "hvac repair"
"""
import argparse
import json
import os
import sys

from . import store
from .heatmap import render_heatmap
from .scanner import run_scan, print_summary

OUT = os.getenv("GRIDSCOUT_OUT", "./output")


def cmd_scan(a):
    meta, pins = run_scan(
        a.business, a.keyword, a.lat, a.lng,
        size=a.size, radius_miles=a.radius, depth=a.depth,
        provider_name=a.provider,
    )
    con = store.connect()
    scan_id = store.save_scan(con, meta, pins)
    meta["scan_id"] = scan_id

    os.makedirs(OUT, exist_ok=True)
    slug = "".join(c if c.isalnum() else "-" for c in a.business.lower()).strip("-")
    base = os.path.join(OUT, f"{slug}-{scan_id}")

    with open(base + ".json", "w") as f:
        json.dump({"meta": meta, "pins": pins}, f, indent=2)
    render_heatmap(meta, pins, base + ".html", depth=a.depth)

    print_summary(meta, pins)
    print(f"  scan #{scan_id}")
    print(f"  {base}.html")
    print(f"  {base}.json\n")


def cmd_history(a):
    con = store.connect()
    rows = store.history(con, a.business, a.keyword)
    if not rows:
        sys.exit("no scans for that business + keyword")
    print(f"\n  {a.business} | \"{a.keyword}\"\n")
    print(f"  {'date':<22}{'vis':>7}{'avg':>8}{'top3%':>8}{'found%':>9}")
    for r in rows:
        print(f"  {r['created_at']:<22}{r['visibility']:>7}"
              f"{(r['avg_rank'] if r['avg_rank'] is not None else 0):>8}"
              f"{r['top3_pct']:>8}{r['found_pct']:>9}")
    print()


def main():
    p = argparse.ArgumentParser(prog="gridscout")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="run a grid scan")
    s.add_argument("--business", required=True)
    s.add_argument("--keyword", required=True)
    s.add_argument("--lat", type=float, required=True)
    s.add_argument("--lng", type=float, required=True)
    s.add_argument("--size", type=int, default=7)
    s.add_argument("--radius", type=float, default=3.0)
    s.add_argument("--depth", type=int, default=20)
    s.add_argument("--provider", default=None, help="mock | dataforseo")
    s.set_defaults(func=cmd_scan)

    h = sub.add_parser("history", help="rank history for a business + keyword")
    h.add_argument("--business", required=True)
    h.add_argument("--keyword", required=True)
    h.set_defaults(func=cmd_history)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
