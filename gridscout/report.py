"""Standalone branded PDF report. The map sells itself, so this does not wrap the
scan in a scoring rubric. It is a cover, the heatmap, the numbers, the written
analysis, and a recommended actions section, in the LNL palette.

The analysis prose comes from the model (already written and cached). The numbers
come from the findings file. The map is drawn as inline SVG so the PDF is fully
self-contained, with no map tiles to fetch.

Rendering goes through WeasyPrint: the importable module first, then the weasyprint
CLI on PATH (the Homebrew install). If neither is present it still writes the HTML.

No em dashes, no scoring banners, and the word the brand avoids never appears.
"""
import html as _html
import os
import re
import shutil
import subprocess

CYAN = "#00e5ff"
PURPLE = "#a855f7"


def _color(rank):
    if rank is None:
        return "#3b4654"
    if rank <= 3:
        return "#00e5ff"
    if rank <= 7:
        return "#6ee7b7"
    if rank <= 12:
        return "#fbbf24"
    return "#fb7185"


def _svg_heatmap(meta, pins):
    size = meta["grid_size"]
    cell = 76
    pad = 30
    dim = size * cell + pad * 2
    r = cell * 0.40
    parts = [
        f'<svg viewBox="0 0 {dim} {dim}" width="100%" '
        f'xmlns="http://www.w3.org/2000/svg" font-family="IBM Plex Mono, monospace">',
        f'<rect x="0" y="0" width="{dim}" height="{dim}" rx="14" fill="#0b0f14" '
        f'stroke="#22303d"/>',
    ]
    grid = {(p["row"], p["col"]): p for p in pins}
    for row in range(size):
        for col in range(size):
            p = grid.get((row, col))
            cx = pad + col * cell + cell / 2
            cy = pad + row * cell + cell / 2
            rank = p["rank"] if p else None
            fill = _color(rank)
            label = "X" if rank is None else str(rank)
            txt = "#04080c" if rank is not None else "#8a9aa8"
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
                         f'fill="{fill}" stroke="rgba(0,0,0,.35)"/>')
            parts.append(f'<text x="{cx:.1f}" y="{cy + 5:.1f}" text-anchor="middle" '
                         f'font-size="20" font-weight="600" fill="{txt}">{label}</text>')
    c = pad + (size / 2) * cell
    parts.append(f'<circle cx="{c:.1f}" cy="{c:.1f}" r="6" fill="none" '
                 f'stroke="{PURPLE}" stroke-width="3"/>')
    parts.append('</svg>')
    return "\n".join(parts)


def _legend():
    rows = [("Rank 1 to 3", "#00e5ff"), ("Rank 4 to 7", "#6ee7b7"),
            ("Rank 8 to 12", "#fbbf24"), ("Rank 13 to 20", "#fb7185"),
            ("Not in top 20", "#3b4654")]
    items = "".join(
        f'<div class="leg"><span class="sw" style="background:{c}"></span>{t}</div>'
        for t, c in rows)
    return f'<div class="legend">{items}</div>'


def _md_to_html(md):
    """Small Markdown to HTML converter, enough for the model's analysis output:
    headings, bold, unordered lists, and paragraphs. Everything is escaped first."""
    def inline(s):
        s = _html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", s)
        return s

    out, in_list = [], False
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            level = min(len(m.group(1)) + 1, 4)  # shift so # becomes h2
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            continue
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def build_html(findings, meta, pins, analysis_md):
    v = findings["visibility"]
    svg = _svg_heatmap(meta, pins)
    cards = "".join(
        f'<div class="card"><div class="cn">{val}</div><div class="cl">{lbl}</div></div>'
        for val, lbl in [
            (v["score"], "Visibility score"),
            (v["avg_rank_where_found"] if v["avg_rank_where_found"] is not None
             else "n/a", "Avg rank"),
            (f'{v["pct_top3"]}%', "Pins in top 3"),
            (f'{v["pct_visible"]}%', "Pins visible"),
            (f'{v["pct_invisible"]}%', "Pins invisible"),
        ])
    biz = _html.escape(findings["business"])
    kw = _html.escape(findings["keyword"])
    analysis_html = _md_to_html(analysis_md)

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Syne:wght@600;800&display=swap');
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:#0b0f14; color:#e6edf3;
       font-family:'IBM Plex Mono', monospace; font-size:11px; line-height:1.55; }}
.page {{ width:210mm; min-height:297mm; padding:22mm 20mm; page-break-after:always; background:#0b0f14; }}
.page:last-child {{ page-break-after:auto; }}
h1 {{ font-family:'Syne',sans-serif; font-weight:800; font-size:34px; margin:0 0 4px; letter-spacing:-.01em; }}
h2 {{ font-family:'Syne',sans-serif; font-weight:800; font-size:20px; margin:0 0 14px; color:{CYAN}; }}
h3 {{ font-family:'Syne',sans-serif; font-weight:700; font-size:14px; margin:18px 0 6px; color:{CYAN}; text-transform:uppercase; letter-spacing:.05em; }}
h4 {{ font-family:'Syne',sans-serif; font-weight:700; font-size:12px; margin:14px 0 5px; color:#e6edf3; }}
.kw {{ color:{CYAN}; font-size:14px; }}
.muted {{ color:#8a9aa8; }}
.brandbar {{ height:4px; width:80px; background:linear-gradient(90deg,{CYAN},{PURPLE}); margin:0 0 40px; border-radius:2px; }}
.cover-lead {{ margin-top:120px; }}
.cover-score {{ font-family:'Syne',sans-serif; font-weight:800; font-size:120px; line-height:1; color:{CYAN}; margin:38px 0 0; }}
.cover-score small {{ font-size:24px; color:#8a9aa8; font-family:'IBM Plex Mono'; }}
.cover-foot {{ margin-top:120px; color:#8a9aa8; font-size:11px; }}
.mapwrap {{ display:flex; gap:20px; align-items:flex-start; }}
.mapwrap .map {{ flex:1; }}
.legend {{ width:150px; }}
.leg {{ display:flex; align-items:center; gap:8px; margin-bottom:8px; color:#8a9aa8; font-size:10px; }}
.sw {{ width:14px; height:14px; border-radius:50%; display:inline-block; }}
.cards {{ display:flex; gap:10px; margin:22px 0 0; }}
.card {{ flex:1; background:#131a22; border:1px solid #22303d; border-radius:8px; padding:14px 12px; }}
.cn {{ font-family:'Syne',sans-serif; font-weight:800; font-size:24px; color:{CYAN}; line-height:1; }}
.cl {{ font-size:9px; color:#8a9aa8; text-transform:uppercase; letter-spacing:.08em; margin-top:6px; }}
.analysis p {{ margin:0 0 10px; color:#c6d2dc; }}
.analysis ul {{ margin:0 0 12px; padding-left:18px; }}
.analysis li {{ margin:0 0 6px; color:#c6d2dc; }}
.analysis strong {{ color:#e6edf3; }}
.foot {{ color:#4a5a68; font-size:9px; margin-top:30px; border-top:1px solid #1a232c; padding-top:10px; }}
</style></head><body>

<div class="page">
  <div class="brandbar"></div>
  <div class="cover-lead">
    <div class="muted" style="letter-spacing:.2em;text-transform:uppercase;font-size:11px">Local Map Visibility Report</div>
    <h1>{biz}</h1>
    <div class="kw">"{kw}"</div>
    <div class="cover-score">{v['score']}<small> / 100 visibility</small></div>
    <div class="muted" style="margin-top:18px">Visible at {v['pct_visible']}% of {findings['grid']['points']} scanned points. Invisible at {v['points_invisible']}.</div>
  </div>
  <div class="cover-foot">
    {meta['grid_size']}x{meta['grid_size']} grid over a {meta['radius_miles']} mile radius &middot; scanned {_html.escape(str(findings.get('scanned_at') or ''))}<br/>
    Prepared by LNL AI Agency &middot; Where human vision meets machine precision
  </div>
</div>

<div class="page">
  <h2>The map</h2>
  <div class="muted" style="margin:-8px 0 18px">Each point is the same search run from that spot. The number is where {biz} lands there. The purple ring is the business location.</div>
  <div class="mapwrap">
    <div class="map">{svg}</div>
    {_legend()}
  </div>
  <div class="cards">{cards}</div>
  <div class="foot">Rank is measured live from each coordinate. Not-found means the business did not appear in the top 20 at that point.</div>
</div>

<div class="page">
  <h2>What the map says</h2>
  <div class="analysis">{analysis_html}</div>
  <div class="foot">Prepared by LNL AI Agency. This report reflects a point-in-time scan. Re-scan monthly to track movement.</div>
</div>

</body></html>"""


def render_pdf(findings, analysis, analysis_md, out_path):
    """Render the report to a PDF. Returns (pdf_path or None, html_path)."""
    meta = analysis["meta"]
    pins = analysis["pins"]
    html_doc = build_html(findings, meta, pins, analysis_md)
    html_path = os.path.splitext(out_path)[0] + ".html"
    with open(html_path, "w") as f:
        f.write(html_doc)

    # 1. importable module (environments where pip installed WeasyPrint)
    try:
        import weasyprint
        weasyprint.HTML(string=html_doc, base_url=".").write_pdf(out_path)
        return out_path, html_path
    except Exception:
        pass

    # 2. the weasyprint CLI on PATH (Homebrew install)
    cli = shutil.which("weasyprint")
    if cli:
        try:
            subprocess.run([cli, html_path, out_path], check=True,
                           capture_output=True, timeout=120)
            return out_path, html_path
        except Exception:
            pass

    return None, html_path
