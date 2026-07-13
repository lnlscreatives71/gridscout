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


def _base(meta):
    return os.path.join(OUT, f"{_slug(meta['business'])}-{meta['scan_id']}")


def _print_spend(dfs_cost, ai_cost, ai_cached):
    """Itemize what this run actually cost. Real figures, never estimates."""
    ai_note = "  (served from cache, no API call)" if ai_cached else ""
    print("\n  Spend this run")
    print(f"    DataForSEO:  ${dfs_cost:.4f}")
    print(f"    Anthropic:   ${ai_cost:.4f}{ai_note}")
    print(f"    Total:       ${dfs_cost + ai_cost:.4f}\n")


def _build_findings(con, sid, use_geo):
    """Load a scan, compute the analysis, and write the findings file.

    Writing findings is a side effect of every analyze run, per the design: it is
    the auditable record the model writes from and the operator can rewrite off.
    Returns (meta, analysis, findings, findings_path).
    """
    from . import analysis as analysis_mod
    from . import findings as findings_mod
    meta, pins = analysis_mod.load(con, store, sid)
    an = analysis_mod.compute(meta, pins)
    fnd = findings_mod.build(an, use_geo=use_geo)
    os.makedirs(OUT, exist_ok=True)
    path = _base(meta) + "-findings.json"
    with open(path, "w") as f:
        json.dump(fnd, f, indent=2)
    return meta, an, fnd, path


def _ensure_analysis(con, sid, findings, refresh):
    """Return the analysis markdown, generating it via the model only if needed.

    Reuses the cached analysis so re-running report or content does not re-bill the
    API. Returns (markdown, ai_cost, cached).
    """
    from . import llm
    row = store.get_ai_output(con, sid, "analysis")
    if row and not refresh:
        return row["content"], 0.0, True
    text, usage, model = llm.write_analysis(findings)
    c = llm.cost(model, usage)
    store.save_ai_output(con, sid, "analysis", model, text,
                         usage["input_tokens"], usage["output_tokens"], c)
    return text, c, False


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
    print(f"  {base}.json")
    _print_spend(meta.get("dfs_cost", 0.0), 0.0, False)


def cmd_analyze(a):
    con = store.connect()
    sid = _resolve_scan_id(con, a.scan_id)
    if not a.no_geo:
        print("  resolving real place names for the scan zones "
              "(OpenStreetMap, a few seconds)...")
    meta, an, fnd, fpath = _build_findings(con, sid, use_geo=not a.no_geo)

    text, ai_cost, cached = _ensure_analysis(con, sid, fnd, refresh=a.refresh)

    base = _base(meta)
    with open(base + "-analysis.md", "w") as f:
        f.write(text + "\n")

    print("\n" + text)
    print(f"\n  findings: {fpath}")
    print(f"  analysis: {base}-analysis.md")
    _print_spend(0.0, ai_cost, cached)


def cmd_content(a):
    from . import content, llm
    con = store.connect()
    sid = _resolve_scan_id(con, a.scan_id)
    if not a.no_geo:
        print("  resolving real place names for the weak zones "
              "(OpenStreetMap, a few seconds)...")
    meta, an, fnd, fpath = _build_findings(con, sid, use_geo=not a.no_geo)

    if not fnd["weak_zones"]:
        print("\n  No weak zones in this scan. Nothing to draft. This business is "
              "visible across the whole grid.")
        _print_spend(0.0, 0.0, False)
        return

    # content builds on the analysis; generate it first if it is not cached yet
    analysis_md, an_cost, an_cached = _ensure_analysis(con, sid, fnd,
                                                       refresh=a.refresh)

    row = store.get_ai_output(con, sid, "content")
    if row and not a.refresh:
        drafts = json.loads(row["content"])
        content_cost, content_cached = 0.0, True
    else:
        drafts, usage, model = llm.write_content(fnd, analysis_md)
        content_cost = llm.cost(model, usage)
        store.save_ai_output(con, sid, "content", model, json.dumps(drafts),
                             usage["input_tokens"], usage["output_tokens"],
                             content_cost)
        content_cached = False

    out_dir = _base(meta) + "-content"
    written = content.assemble(fnd, drafts, out_dir)

    print(f"\n  Drafts for {meta['business']} written to {out_dir}\n")
    for path in written:
        print(f"    {path}")
    print("\n  Nothing was published. Review, add your local detail, then post.")
    _print_spend(0.0, an_cost + content_cost, an_cached and content_cached)


def cmd_report(a):
    from . import report
    con = store.connect()
    sid = _resolve_scan_id(con, a.scan_id)
    if not a.no_geo:
        print("  resolving real place names for the scan zones "
              "(OpenStreetMap, a few seconds)...")
    meta, an, fnd, fpath = _build_findings(con, sid, use_geo=not a.no_geo)

    # the report needs the analysis; generate it only if it is not already cached
    analysis_md, ai_cost, cached = _ensure_analysis(con, sid, fnd, refresh=a.refresh)

    base = _base(meta)
    pdf_path, html_path = report.render_pdf(fnd, an, analysis_md, base + "-report.pdf")

    if pdf_path:
        print(f"\n  report: {pdf_path}")
    else:
        print(f"\n  WeasyPrint was not available, so the PDF was not built.")
        print(f"  The report HTML is ready to print to PDF from a browser:")
        print(f"    {html_path}")
    _print_spend(0.0, ai_cost, cached)


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

    an = sub.add_parser("analyze", help="AI ranking analysis of a scan")
    an.add_argument("scan_id", type=int, nargs="?", default=None,
                    help="scan id (default: latest)")
    an.add_argument("--refresh", action="store_true",
                    help="regenerate the analysis even if one is cached")
    an.add_argument("--no-geo", action="store_true",
                    help="skip OpenStreetMap lookups, use directional names only")
    an.set_defaults(func=cmd_analyze)

    c = sub.add_parser("content", help="draft service-area pages, GBP posts, schema")
    c.add_argument("scan_id", type=int, nargs="?", default=None,
                   help="scan id (default: latest)")
    c.add_argument("--refresh", action="store_true",
                   help="regenerate drafts even if they are cached")
    c.add_argument("--no-geo", action="store_true",
                   help="skip OpenStreetMap lookups, use directional names only")
    c.set_defaults(func=cmd_content)

    r = sub.add_parser("report", help="branded PDF heatmap report")
    r.add_argument("scan_id", type=int, nargs="?", default=None,
                   help="scan id (default: latest)")
    r.add_argument("--refresh", action="store_true",
                   help="regenerate the analysis even if one is cached")
    r.add_argument("--no-geo", action="store_true",
                   help="skip OpenStreetMap lookups, use directional names only")
    r.set_defaults(func=cmd_report)

    h = sub.add_parser("history", help="rank history for a business + keyword")
    h.add_argument("--business", required=True)
    h.add_argument("--keyword", required=True)
    h.set_defaults(func=cmd_history)

    a = p.parse_args()
    try:
        a.func(a)
    except RuntimeError as e:
        # clean, actionable message (missing API key, missing package) instead
        # of a traceback
        sys.exit(f"\n{e}\n")


if __name__ == "__main__":
    main()
