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
import base64
import html as _html
import math
import os
import re
import shutil
import subprocess
import urllib.request

CYAN = "#00e5ff"
PURPLE = "#a855f7"

# Where the report's call to action points. Change these in one place.
BOOKING_URL = "https://lnlcrm.com/book/discovery-call"
CONTACT_EMAIL = "lainiem@lnlaiagency.com"


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


def _global_px(lat, lng, zoom):
    """Web Mercator pixel coordinate at a zoom (256 px tiles)."""
    n = 256.0 * (2 ** zoom)
    x = (lng + 180.0) / 360.0 * n
    siny = math.sin(math.radians(lat))
    siny = min(max(siny, -0.9999), 0.9999)
    y = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * n
    return x, y


def _real_place(name):
    """A real place name worth labeling, not a directional fallback."""
    if not name:
        return False
    low = name.lower()
    return name[0].isupper() and "edge" not in low and "side" not in low


def _zone_labels(findings, analysis):
    """Real neighborhood names with map coordinates, so the map names the areas
    the pitch talks about. Weak zones first, since those are the ones being lost.
    findings zones carry the geocoded names, analysis zones carry the centroids,
    and they are built in the same order, so they line up."""
    labels, seen = [], set()
    pairs = (list(zip(analysis["weak_zones"], findings["weak_zones"]))
             + list(zip(analysis["strong_zones"], findings["strong_zones"])))
    for za, zf in pairs:
        name = zf.get("place")
        if _real_place(name) and name not in seen:
            seen.add(name)
            labels.append({"lat": za["centroid_lat"], "lng": za["centroid_lng"],
                           "text": name})
        if len(labels) >= 5:
            break
    return labels


def _static_map_svg(meta, pins, labels=None, target_px=760, timeout=8):
    """A real basemap for the PDF: CARTO dark tiles stitched behind the rank pins.

    Fetches the tiles covering the scan area, embeds them as data URIs so the SVG
    is fully self-contained (no network at render time, prints anywhere), and
    overlays the numbered pins projected to the right pixels. Returns None if the
    tiles cannot be fetched, so the caller can fall back to the schematic grid.
    """
    lats = [p["lat"] for p in pins]
    lngs = [p["lng"] for p in pins]
    pad_lat = (max(lats) - min(lats)) * 0.14 or 0.01
    pad_lng = (max(lngs) - min(lngs)) * 0.14 or 0.01
    north, south = max(lats) + pad_lat, min(lats) - pad_lat
    west, east = min(lngs) - pad_lng, max(lngs) + pad_lng

    zoom = 16
    while zoom > 1:
        x0, y0 = _global_px(north, west, zoom)
        x1, y1 = _global_px(south, east, zoom)
        if (x1 - x0) <= target_px and (y1 - y0) <= target_px:
            break
        zoom -= 1

    x0, y0 = _global_px(north, west, zoom)
    x1, y1 = _global_px(south, east, zoom)
    W, H = int(round(x1 - x0)), int(round(y1 - y0))
    if W < 10 or H < 10:
        return None

    subs = "abcd"
    tiles = []
    for ty in range(int(y0 // 256), int(y1 // 256) + 1):
        for tx in range(int(x0 // 256), int(x1 // 256) + 1):
            sub = subs[(tx + ty) % 4]
            # @2x retina tiles: twice the detail, so street and place labels are
            # legible in print. dark_all carries CARTO's street and place labels.
            url = (f"https://{sub}.basemaps.cartocdn.com/dark_all/"
                   f"{zoom}/{tx}/{ty}@2x.png")
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "gridscout/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = r.read()
            except Exception:
                return None
            b64 = base64.b64encode(data).decode()
            ox, oy = tx * 256 - x0, ty * 256 - y0
            tiles.append(f'<image x="{ox:.1f}" y="{oy:.1f}" width="256" '
                         f'height="256" xlink:href="data:image/png;base64,{b64}"/>')
    if not tiles:
        return None

    # pin radius from the actual spacing between neighboring pins
    centers = [(_global_px(p["lat"], p["lng"], zoom), p) for p in pins]
    xs = sorted({round(c[0][0], 1) for c in centers})
    spacing = min((b - a for a, b in zip(xs, xs[1:])), default=40) if len(xs) > 1 else 40
    r = max(9.0, min(20.0, spacing * 0.42))

    pin_svg = []
    for (gx, gy), p in centers:
        cx, cy = gx - x0, gy - y0
        rank = p["rank"]
        fill = _color(rank)
        label = "X" if rank is None else str(rank)
        txt = "#04080c" if rank is not None else "#c9d4de"
        # gray "not found" pins sit lighter so the map and its labels show through
        op = 0.62 if rank is None else 0.86
        pin_svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
                       f'fill="{fill}" fill-opacity="{op}" stroke="#04080c" '
                       f'stroke-opacity="0.45" stroke-width="1"/>')
        pin_svg.append(f'<text x="{cx:.1f}" y="{cy + r * 0.34:.1f}" '
                       f'text-anchor="middle" font-size="{r * 0.95:.0f}" '
                       f'font-weight="600" fill="{txt}" '
                       f'font-family="IBM Plex Mono, monospace">{label}</text>')
    cgx, cgy = _global_px(meta["center_lat"], meta["center_lng"], zoom)
    pin_svg.append(f'<circle cx="{cgx - x0:.1f}" cy="{cgy - y0:.1f}" r="5" '
                   f'fill="none" stroke="{PURPLE}" stroke-width="3"/>')

    # neighborhood name labels, drawn on top so they are readable over the pins
    label_svg = []
    for lb in (labels or []):
        lgx, lgy = _global_px(lb["lat"], lb["lng"], zoom)
        lx, ly = lgx - x0, lgy - y0
        if not (6 <= lx <= W - 6 and 6 <= ly <= H - 6):
            continue
        txt = _html.escape(lb["text"])
        w = len(lb["text"]) * 6.6 + 14
        lx = min(max(lx, w / 2 + 2), W - w / 2 - 2)
        label_svg.append(
            f'<rect x="{lx - w / 2:.1f}" y="{ly - 9:.1f}" width="{w:.1f}" '
            f'height="17" rx="8.5" fill="#0b0f14" fill-opacity="0.86" '
            f'stroke="{CYAN}" stroke-opacity="0.55" stroke-width="0.75"/>')
        label_svg.append(
            f'<text x="{lx:.1f}" y="{ly + 3:.1f}" text-anchor="middle" '
            f'font-size="10.5" font-weight="600" fill="{CYAN}" '
            f'font-family="IBM Plex Mono, monospace">{txt}</text>')

    return (f'<svg viewBox="0 0 {W} {H}" width="100%" '
            f'xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink">'
            f'<rect width="{W}" height="{H}" fill="#0b0f14"/>'
            + "".join(tiles) + "".join(pin_svg) + "".join(label_svg)
            + f'<rect width="{W}" height="{H}" fill="none" stroke="#22303d" '
            f'rx="8"/></svg>')


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
    rows = [("Top 3 results", "#00e5ff"), ("4th to 7th", "#6ee7b7"),
            ("8th to 12th", "#fbbf24"), ("13th to 20th", "#fb7185"),
            ("Does not show up", "#3b4654")]
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


def build_html(findings, meta, pins, analysis_md, labels=None, use_basemap=True):
    v = findings["visibility"]
    # a real stitched basemap when the tiles are reachable, otherwise the
    # self-contained schematic grid so the report still builds offline
    svg = (_static_map_svg(meta, pins, labels=labels) if use_basemap else None) \
        or _svg_heatmap(meta, pins)
    reach = findings.get("reach") or {}
    far = reach.get("farthest_you_appear_miles")
    near = reach.get("closest_you_vanish_miles")
    span = meta["radius_miles"] * 2
    cards = "".join(
        f'<div class="card"><div class="cn">{val}</div><div class="cl">{lbl}</div></div>'
        for val, lbl in [
            (f'{far} mi' if far is not None else "n/a", "Shows up out to"),
            (f'{near} mi' if near is not None else "n/a", "Gone by (weak side)"),
            (f'{v["pct_visible"]}%', "Area you show up in"),
            (f'{v["pct_top3"]}%', "Area you are top 3"),
            (v["score"], "Visibility score / 100"),
        ])
    biz = _html.escape(findings["business"])
    kw = _html.escape(findings["keyword"])
    analysis_html = _md_to_html(analysis_md)

    # The cover leads with whichever number is the real story. "Shows up out to
    # N miles" is honest when the business genuinely shows up around its shop;
    # for a business missing from most of the area it softens a presence
    # problem into geography, so those covers lead with the missing places.
    center = min(pins, key=lambda p: p["dist_miles"])
    gone_at_own_door = center["rank"] is None or center["rank"] > 3
    if v["pct_visible"] < 25 or (v["pct_top3"] == 0 and v["pct_visible"] < 50):
        n = findings["grid"]["points"]
        never_top3 = (
            " It was never one of the first three results anywhere we checked"
            + (", not even standing at its own front door." if gone_at_own_door
               else ".")) if v["pct_top3"] == 0 else ""
        cover_hero = f"""<div class="cover-score">{v['points_invisible']} of {n}<small> places</small></div>
    <div class="muted" style="margin-top:18px">We checked {n} places around the shop. In {v['points_invisible']} of them, {biz} does not show up on Google Maps at all when people search for {kw}.{never_top3} Every one of those searches ends at a competitor instead.</div>"""
    else:
        cover_hero = f"""<div class="cover-score">{far if far is not None else '-'}<small> miles</small></div>
    <div class="muted" style="margin-top:18px">That is how far from the shop {biz} shows up on Google Maps at best. In its weakest direction it is gone by about {near} mile. Everywhere past that edge, all of it, the people searching for {kw} are finding a competitor instead.</div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Syne:wght@600;800&display=swap');
/* margin on every physical sheet, including pages the analysis overflows onto,
   so text never runs to the paper edge. The dark background is set on html so it
   propagates to the whole sheet (margins included) and the report stays full
   bleed dark. */
/* Paint the dark on @page so the whole sheet, margins included, stays full
   bleed dark on every physical page, while the margin keeps text off the edges,
   including on pages a long analysis overflows onto. */
@page {{ size: A4; margin: 16mm; background: #0b0f14; }}
* {{ box-sizing: border-box; }}
html, body {{ background:#0b0f14; }}
body {{ margin:0; color:#e6edf3;
       font-family:'IBM Plex Mono', ui-monospace, Menlo, monospace; font-size:11px; line-height:1.55; }}
.page {{ page-break-after:always; }}
.page:last-child {{ page-break-after:auto; }}
h1 {{ font-family:'Syne', system-ui, sans-serif; font-weight:800; font-size:34px; line-height:1.15; margin:0 0 4px; letter-spacing:-.01em; }}
h2 {{ font-family:'Syne', system-ui, sans-serif; font-weight:800; font-size:20px; margin:0 0 14px; color:{CYAN}; }}
h3 {{ font-family:'Syne', system-ui, sans-serif; font-weight:700; font-size:14px; margin:18px 0 6px; color:{CYAN}; text-transform:uppercase; letter-spacing:.05em; }}
h4 {{ font-family:'Syne', system-ui, sans-serif; font-weight:700; font-size:12px; margin:14px 0 5px; color:#e6edf3; }}
.kw {{ color:{CYAN}; font-size:14px; }}
.muted {{ color:#8a9aa8; }}
.brandbar {{ height:4px; width:80px; background:linear-gradient(90deg,{CYAN},{PURPLE}); margin:0 0 40px; border-radius:2px; }}
.cover-lead {{ margin-top:96px; }}
.cover-score {{ font-family:'Syne', system-ui, sans-serif; font-weight:800; font-size:104px; line-height:1.12; color:{CYAN}; margin:44px 0 0; }}
.cover-score small {{ font-size:24px; color:#8a9aa8; font-family:'IBM Plex Mono', ui-monospace, monospace; }}
.cover-foot {{ color:#8a9aa8; font-size:11px; margin-top:64px; }}
.mapwrap {{ display:flex; gap:20px; align-items:flex-start; }}
.mapwrap .map {{ flex:1; }}
.legend {{ width:150px; }}
.leg {{ display:flex; align-items:center; gap:8px; margin-bottom:8px; color:#8a9aa8; font-size:10px; }}
.sw {{ width:14px; height:14px; border-radius:50%; display:inline-block; }}
.cards {{ display:flex; gap:10px; margin:22px 0 0; }}
.card {{ flex:1; background:#131a22; border:1px solid #22303d; border-radius:8px; padding:14px 12px; }}
.cn {{ font-family:'Syne', system-ui, sans-serif; font-weight:800; font-size:24px; color:{CYAN}; line-height:1.15; }}
.cl {{ font-size:9px; color:#8a9aa8; text-transform:uppercase; letter-spacing:.08em; margin-top:6px; }}
.analysis p {{ margin:0 0 10px; color:#c6d2dc; }}
.analysis ul {{ margin:0 0 12px; padding-left:18px; }}
.analysis li {{ margin:0 0 6px; color:#c6d2dc; }}
.analysis strong {{ color:#e6edf3; }}
.cta {{ margin-top:26px; padding:20px 22px; border:1px solid #22303d; border-radius:10px;
        background:linear-gradient(180deg, rgba(0,229,255,.06), rgba(168,85,247,.06)); }}
.cta-h {{ font-family:'Syne', system-ui, sans-serif; font-weight:800; font-size:18px; color:{CYAN}; margin-bottom:6px; }}
.cta-p {{ color:#c6d2dc; margin-bottom:12px; }}
.cta-row {{ color:#e6edf3; font-size:12px; margin-top:4px; }}
.cta-k {{ display:inline-block; min-width:78px; color:#8a9aa8; text-transform:uppercase; letter-spacing:.06em; font-size:10px; }}
.foot {{ color:#4a5a68; font-size:9px; margin-top:24px; border-top:1px solid #1a232c; padding-top:10px; }}
</style></head><body>

<div class="page cover">
  <div class="brandbar"></div>
  <div class="cover-lead">
    <div class="muted" style="letter-spacing:.2em;text-transform:uppercase;font-size:11px">Local Map Visibility Report</div>
    <h1>{biz}</h1>
    <div class="kw">"{kw}"</div>
    {cover_hero}
  </div>
  <div class="cover-foot">
    We checked {findings['grid']['points']} places across about {span:.0f} miles around the business &middot; {_html.escape(str(findings.get('scanned_at') or ''))}<br/>
    Prepared by LNL AI Agency &middot; Where human vision meets machine precision
  </div>
</div>

<div class="page">
  <h2>The map</h2>
  <div class="muted" style="margin:-8px 0 18px">Each dot is a place we checked near the business. The number is how high {biz} showed up there, so 1 is the very top. Gray means it did not show up at all, and everything past the gray edge is the same story. The purple ring is the business itself.</div>
  <div class="mapwrap">
    <div class="map">{svg}</div>
    {_legend()}
  </div>
  <div class="cards">{cards}</div>
  <div class="foot">We ran the same Google Maps search from every dot. Gray means the business did not come up in the first twenty results there, so a customer standing at that spot would not see it. The whole area beyond the colored dots looks the same way.</div>
</div>

<div class="page">
  <h2>What this means for your business</h2>
  <div class="analysis">{analysis_html}</div>
  <div class="cta">
    <div class="cta-h">Ready to win back those customers?</div>
    <div class="cta-p">Pushing your visible edge outward takes sustained, expert local search work. That is what LNL AI Agency does. Let's talk about turning the gray on this map into your customers.</div>
    <div class="cta-row"><span class="cta-k">Book a call</span> {BOOKING_URL}</div>
    <div class="cta-row"><span class="cta-k">Email</span> {CONTACT_EMAIL}</div>
  </div>
  <div class="foot">Prepared by LNL AI Agency &middot; Where human vision meets machine precision &middot; This reflects one moment in time.</div>
</div>

</body></html>"""


def render_pdf(findings, analysis, analysis_md, out_path):
    """Render the report to a PDF. Returns (pdf_path or None, html_path)."""
    meta = analysis["meta"]
    pins = analysis["pins"]
    labels = _zone_labels(findings, analysis)
    html_doc = build_html(findings, meta, pins, analysis_md, labels=labels)
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
