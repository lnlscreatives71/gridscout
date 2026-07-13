"""Interactive HTML heatmap. Leaflet + OSM tiles, no Google Maps key needed.

Includes the competitor overlay: pick any business that appeared anywhere in the
scan and the pins re-render showing THEIR rank at each point.
"""
import json

TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{business} - Grid Scan</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preconnect" href="https://basemaps.cartocdn.com">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Syne:wght@600;800&display=swap" rel="stylesheet">
<style>
  :root {{ --bg:#0b0f14; --panel:#131a22; --line:#22303d; --cyan:#00e5ff; --purple:#a855f7; --txt:#e6edf3; --dim:#8a9aa8; }}
  * {{ box-sizing:border-box; }}
  html, body {{ height:100%; }}
  body {{ margin:0; background:var(--bg); color:var(--txt); line-height:1.5;
          font-family:'IBM Plex Mono', ui-monospace, Menlo, monospace;
          display:flex; flex-direction:column; height:100vh; }}
  header {{ flex:0 0 auto; padding:16px 24px; border-bottom:1px solid var(--line);
            display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }}
  h1 {{ font-family:'Syne', system-ui, sans-serif; font-weight:800; font-size:20px;
        line-height:1.25; margin:0; letter-spacing:-.01em; }}
  .kw {{ color:var(--cyan); font-size:13px; }}
  .wrap {{ flex:1 1 auto; min-height:0; display:grid; grid-template-columns:1fr 300px; }}
  /* a faint grid so the surface reads as a dark map even before tiles paint */
  #map {{ height:100%; min-height:0; background-color:#0b0f14;
          background-image:linear-gradient(#131c26 1px, transparent 1px),
                           linear-gradient(90deg, #131c26 1px, transparent 1px);
          background-size:48px 48px; }}
  .leaflet-container {{ font-family:'IBM Plex Mono', ui-monospace, Menlo, monospace; }}
  aside {{ background:var(--panel); border-left:1px solid var(--line); padding:20px; overflow:auto; }}
  .stat {{ margin-bottom:16px; }}
  .stat .n {{ font-family:'Syne',sans-serif; font-size:28px; font-weight:800; color:var(--cyan); line-height:1; }}
  .stat .l {{ font-size:11px; color:var(--dim); text-transform:uppercase; letter-spacing:.08em; margin-top:4px; }}
  h2 {{ font-family:'Syne',sans-serif; font-size:12px; text-transform:uppercase; letter-spacing:.1em; color:var(--dim); border-top:1px solid var(--line); padding-top:16px; margin:20px 0 10px; }}
  select {{ width:100%; background:#0b0f14; color:var(--txt); border:1px solid var(--line); padding:8px; font-family:inherit; font-size:12px; border-radius:4px; }}
  .legend {{ display:flex; flex-direction:column; gap:6px; font-size:11px; color:var(--dim); }}
  .legend i {{ display:inline-block; width:12px; height:12px; border-radius:50%; margin-right:8px; vertical-align:-1px; }}
  .pin {{ border-radius:50%; display:flex; align-items:center; justify-content:center;
          font:600 11px 'IBM Plex Mono',monospace; color:#04080c; border:1px solid rgba(0,0,0,.35);
          box-shadow:0 0 8px rgba(0,0,0,.5); }}
  .leaflet-popup-content-wrapper {{ background:var(--panel); color:var(--txt); border-radius:6px; }}
  .leaflet-popup-tip {{ background:var(--panel); }}
  .pop b {{ color:var(--cyan); }}
  .pop ol {{ margin:6px 0 0; padding-left:18px; font-size:11px; color:var(--dim); }}
  .pop li.me {{ color:var(--cyan); font-weight:600; }}
</style></head><body>
<header>
  <h1>{business}</h1><span class="kw">"{keyword}"</span>
  <span style="color:var(--dim);font-size:11px">{grid_size}x{grid_size} grid &middot; {radius} mi radius &middot; {created}</span>
</header>
<div class="wrap">
  <div id="map"></div>
  <aside>
    <div class="stat"><div class="n" id="s-vis">-</div><div class="l">Visibility score</div></div>
    <div class="stat"><div class="n" id="s-avg">-</div><div class="l">Avg rank where found</div></div>
    <div class="stat"><div class="n" id="s-top3">-</div><div class="l">Pins in top 3</div></div>
    <div class="stat"><div class="n" id="s-found">-</div><div class="l">Pins where visible</div></div>
    <h2>Competitor overlay</h2>
    <select id="who"></select>
    <h2>Legend</h2>
    <div class="legend">
      <div><i style="background:#00e5ff"></i>Rank 1-3</div>
      <div><i style="background:#6ee7b7"></i>Rank 4-7</div>
      <div><i style="background:#fbbf24"></i>Rank 8-12</div>
      <div><i style="background:#fb7185"></i>Rank 13-20</div>
      <div><i style="background:#3b4654"></i>Not in top 20</div>
    </div>
  </aside>
</div>
<script>
const PINS = {pins_json};
const TARGET = {business_json};
const DEPTH = {depth};

const map = L.map('map', {{zoomControl:true}}).setView([{clat},{clng}], 12);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
  {{subdomains:'abcd', attribution:'&copy; OpenStreetMap, &copy; CARTO',
    maxZoom:19, crossOrigin:true}}).addTo(map);

// Leaflet measures the container at init. In a flex layout that size is not
// final until the browser finishes layout, and if it measures too early the
// basemap never requests the visible tiles (you see the pins but no map). Force
// a remeasure once the map is ready, once on load, and once more after layout
// settles, so the tiles always fill.
function fit() {{ map.invalidateSize(); }}
map.whenReady(fit);
window.addEventListener('load', fit);
window.addEventListener('resize', fit);
setTimeout(fit, 300);

function color(r) {{
  if (r === null) return '#3b4654';
  if (r <= 3) return '#00e5ff';
  if (r <= 7) return '#6ee7b7';
  if (r <= 12) return '#fbbf24';
  return '#fb7185';
}}

const names = new Set();
PINS.forEach(p => p.results.forEach(r => names.add(r.name)));
const sel = document.getElementById('who');
[...names].sort().forEach(n => {{
  const o = document.createElement('option');
  o.value = n; o.textContent = n; if (n === TARGET) o.selected = true;
  sel.appendChild(o);
}});

let layer = L.layerGroup().addTo(map);

function rankFor(pin, who) {{
  const hit = pin.results.find(r => r.name === who);
  return hit ? hit.rank : null;
}}

function render(who) {{
  layer.clearLayers();
  let found = [], top3 = 0;
  PINS.forEach(p => {{
    const r = rankFor(p, who);
    if (r !== null) {{ found.push(r); if (r <= 3) top3++; }}
    const size = 30;
    const icon = L.divIcon({{
      className: '',
      html: `<div class="pin" style="width:${{size}}px;height:${{size}}px;background:${{color(r)}}">${{r===null?'X':r}}</div>`,
      iconSize: [size, size], iconAnchor: [size/2, size/2]
    }});
    const list = p.results.slice(0,5).map(x =>
      `<li class="${{x.name===who?'me':''}}">${{x.name}}</li>`).join('');
    L.marker([p.lat, p.lng], {{icon}})
      .bindPopup(`<div class="pop"><b>${{who}}</b>: ${{r===null?'not in top '+DEPTH:'#'+r}}
        <div style="color:var(--dim);font-size:11px;margin-top:4px">${{p.dist_miles}} mi from center</div>
        <ol>${{list}}</ol></div>`)
      .addTo(layer);
  }});
  const n = PINS.length;
  const vis = PINS.reduce((a,p) => {{
    const r = rankFor(p, who);
    return a + (r === null ? 0 : Math.max(0,(DEPTH-(r-1))/DEPTH));
  }}, 0) / n * 100;
  document.getElementById('s-vis').textContent = vis.toFixed(1);
  document.getElementById('s-avg').textContent = found.length
    ? (found.reduce((a,b)=>a+b,0)/found.length).toFixed(1) : '-';
  document.getElementById('s-top3').textContent = (top3/n*100).toFixed(0) + '%';
  document.getElementById('s-found').textContent = (found.length/n*100).toFixed(0) + '%';
}}

sel.addEventListener('change', e => render(e.target.value));
render(TARGET);
</script></body></html>"""


def render_heatmap(meta, pins, path: str, depth: int = 20):
    slim = [{
        "row": p["row"], "col": p["col"], "lat": p["lat"], "lng": p["lng"],
        "dist_miles": p["dist_miles"], "rank": p["rank"],
        "results": p["results"],
    } for p in pins]

    html = TEMPLATE.format(
        business=meta["business"],
        business_json=json.dumps(meta["business"]),
        keyword=meta["keyword"],
        grid_size=meta["grid_size"],
        radius=meta["radius_miles"],
        created=meta.get("created_at", ""),
        clat=meta["center_lat"], clng=meta["center_lng"],
        pins_json=json.dumps(slim),
        depth=depth,
    )
    with open(path, "w") as f:
        f.write(html)
    return path
