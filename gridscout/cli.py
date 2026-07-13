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


def _slug(text):
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def _resolve_scan_id(con, wanted):
    """Return an explicit scan id, or the latest if none was given."""
    if wanted:
        return wanted
    sid = store.latest_scan_id(con)
    if not sid:
        sys.exit("no scans yet. run a scan first.")
    return sid


def _load_analysis(scan_id=None):
    """Load a scan from the store and run the shared analysis over it."""
    from . import analysis
    con = store.connect()
    sid = _resolve_scan_id(con, scan_id)
    meta, pins = analysis.load(con, store, sid)
    return analysis.compute(meta, pins)


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
    base = os.path.join(OUT, f"{_slug(a.business)}-{scan_id}")

    with open(base + ".json", "w") as f:
        json.dump({"meta": meta, "pins": pins}, f, indent=2)
    render_heatmap(meta, pins, base + ".html", depth=a.depth)

    print_summary(meta, pins)
    print(f"  scan #{scan_id}")
    print(f"  {base}.html")
    print(f"  {base}.json\n")


def cmd_analyze(a):
    from .analyze import render
    analysis = _load_analysis(a.scan_id)
    text = render(analysis)
    print("\n" + text)

    os.makedirs(OUT, exist_ok=True)
    m = analysis["meta"]
    base = os.path.join(OUT, f"{_slug(m['business'])}-{m['scan_id']}-analysis")
    with open(base + ".md", "w") as f:
        f.write(text + "\n")
    print(f"\n  saved: {base}.md\n")


def cmd_content(a):
    from . import content
    analysis = _load_analysis(a.scan_id)
    m = analysis["meta"]
    if not analysis["weak_zones"]:
        print("\n  No weak zones in this scan. Nothing to draft. You are strong "
              "across the whole grid.\n")
        return
    out_dir = os.path.join(OUT, f"{_slug(m['business'])}-{m['scan_id']}-content")
    use_geo = not a.no_geo
    if use_geo:
        print("  resolving real place names for the weak zones "
              "(OpenStreetMap, a few seconds)...")
    manifest = content.generate(analysis, out_dir, use_geo=use_geo)
    print(f"\n  Drafts for {m['business']} written to {out_dir}\n")
    for f in manifest["files"]:
        print(f"    {f}")
    print(f"\n  Zones covered: {', '.join(manifest['area_labels'])}")
    print("  Nothing was published. Review, add your local detail, then post.\n")


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

    an = sub.add_parser("analyze", help="written ranking analysis of a scan")
    an.add_argument("scan_id", type=int, nargs="?", default=None,
                    help="scan id (default: latest)")
    an.set_defaults(func=cmd_analyze)

    c = sub.add_parser("content", help="draft service-area pages, GBP posts, schema")
    c.add_argument("scan_id", type=int, nargs="?", default=None,
                   help="scan id (default: latest)")
    c.add_argument("--no-geo", action="store_true",
                   help="skip OpenStreetMap lookups, use directional names only")
    c.set_defaults(func=cmd_content)

    h = sub.add_parser("history", help="rank history for a business + keyword")
    h.add_argument("--business", required=True)
    h.add_argument("--keyword", required=True)
    h.set_defaults(func=cmd_history)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
