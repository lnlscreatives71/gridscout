"""gridscout web UI. A thin FastAPI layer over the same pipeline the CLI runs.

Single-user internal tool, version one of web gridscout: a form that takes a
business, keyword, and street address, geocodes it, runs the scan in a
background thread, and serves the heatmap and the pitch PDF from the output
directory. No queue, no accounts. The lead-magnet version, if it ever exists,
is this app plus auth, caps, and a stripped response, not a rewrite.

Run it locally:

    source .env
    .venv/bin/python -m uvicorn gridscout.webapp:app --reload

Auth: set GRIDSCOUT_WEB_PASSWORD to require HTTP basic auth (user is
GRIDSCOUT_WEB_USER, default "lnl"). Unset means open, for localhost use only.
"""
import json
import os
import secrets
import threading
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import store
from .cli import OUT, _build_findings, _ensure_analysis, _slug
from .heatmap import render_heatmap
from .scanner import run_scan

app = FastAPI(title="gridscout")

# ---------------------------------------------------------------- auth

_basic = HTTPBasic(auto_error=False)


def _auth(credentials: HTTPBasicCredentials | None = Depends(_basic)):
    password = os.getenv("GRIDSCOUT_WEB_PASSWORD")
    if not password:
        return
    user = os.getenv("GRIDSCOUT_WEB_USER", "lnl")
    ok = (credentials is not None
          and secrets.compare_digest(credentials.username, user)
          and secrets.compare_digest(credentials.password, password))
    if not ok:
        raise HTTPException(401, "unauthorized",
                            headers={"WWW-Authenticate": "Basic"})


# ---------------------------------------------------------------- geocoding

def geocode(address: str):
    """Street address -> (lat, lng, matched_address).

    Census first: it is free, keyless, and exact on street numbers. Nominatim
    as fallback for what Census cannot match (it silently drops street numbers
    and returns the wrong town often enough that it cannot be primary).
    """
    q = urllib.parse.quote(address)
    url = ("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
           f"?address={q}&benchmark=Public_AR_Current&format=json")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            matches = json.load(resp)["result"]["addressMatches"]
        if matches:
            c = matches[0]["coordinates"]
            return c["y"], c["x"], matches[0]["matchedAddress"]
    except Exception:
        pass

    url = f"https://nominatim.openstreetmap.org/search?format=json&limit=1&q={q}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "gridscout/1.0 (lainiem@lnlaiagency.com)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            hits = json.load(resp)
        if hits:
            h = hits[0]
            return float(h["lat"]), float(h["lon"]), h["display_name"]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- jobs

# In-memory job registry. One user, jobs die with the process; the scans
# themselves are already persistent in the store, so nothing of value is lost
# on restart.
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _start_job(kind: str, label: str, work):
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "kind": kind, "label": label, "status": "running",
           "detail": "", "result": None,
           "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with _jobs_lock:
        _jobs[job_id] = job

    def runner():
        try:
            job["result"] = work()
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"
            job["detail"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=runner, daemon=True).start()
    return job_id


# ---------------------------------------------------------------- pipeline

def _scan_files(business: str, scan_id: int):
    base = f"{_slug(business)}-{scan_id}"
    out = {}
    for key, suffix in (("map", ".html"), ("data", ".json"),
                        ("report", "-report.pdf")):
        name = base + suffix
        if os.path.exists(os.path.join(OUT, name)):
            out[key] = f"/output/{name}"
    return out


def _do_scan(business, keyword, lat, lng, size, radius):
    # 3 workers, not the scanner's default 8: DataForSEO throttles bursts with
    # HTTP 402, and the provider's retries make 8 workers slower, not faster.
    meta, pins = run_scan(business, keyword, lat, lng, size=size,
                          radius_miles=radius, provider_name="dataforseo",
                          workers=3)
    con = store.connect()
    scan_id = store.save_scan(con, meta, pins)
    meta["scan_id"] = scan_id

    os.makedirs(OUT, exist_ok=True)
    base = os.path.join(OUT, f"{_slug(business)}-{scan_id}")
    with open(base + ".json", "w") as f:
        json.dump({"meta": meta, "pins": pins}, f, indent=2)
    render_heatmap(meta, pins, base + ".html", depth=20)

    return {"scan_id": scan_id, "visibility": meta["visibility"],
            "avg_rank": meta["avg_rank"], "top3_pct": meta["top3_pct"],
            "found_pct": meta["found_pct"], "dfs_cost": meta["dfs_cost"],
            "files": _scan_files(business, scan_id)}


def _do_report(scan_id: int):
    from . import report
    con = store.connect()
    meta, an, fnd, _ = _build_findings(con, scan_id, use_geo=True)
    analysis_md, ai_cost, cached = _ensure_analysis(con, scan_id, fnd,
                                                    refresh=False)
    base = os.path.join(OUT, f"{_slug(meta['business'])}-{scan_id}")
    pdf_path, html_path = report.render_pdf(fnd, an, analysis_md,
                                            base + "-report.pdf")
    return {"scan_id": scan_id, "pdf": bool(pdf_path), "ai_cost": ai_cost,
            "ai_cached": cached,
            "files": _scan_files(meta["business"], scan_id)}


# ---------------------------------------------------------------- api

class ScanRequest(BaseModel):
    business: str
    keyword: str
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    size: int = 7
    radius: float = 2.0


@app.post("/api/scan", dependencies=[Depends(_auth)])
def api_scan(r: ScanRequest):
    if r.size < 3 or r.size > 9 or r.radius <= 0 or r.radius > 10:
        raise HTTPException(422, "size must be 3-9 and radius 0-10 miles")
    lat, lng, matched = r.lat, r.lng, None
    if lat is None or lng is None:
        if not r.address:
            raise HTTPException(422, "give an address or lat+lng")
        hit = geocode(r.address)
        if not hit:
            raise HTTPException(422, f"could not geocode: {r.address!r}")
        lat, lng, matched = hit
    job_id = _start_job(
        "scan", f'{r.business} | "{r.keyword}"',
        lambda: _do_scan(r.business, r.keyword, lat, lng, r.size, r.radius))
    return {"job_id": job_id, "lat": lat, "lng": lng,
            "matched_address": matched}


@app.post("/api/report/{scan_id}", dependencies=[Depends(_auth)])
def api_report(scan_id: int):
    con = store.connect()
    if not store.get_scan(con, scan_id):
        raise HTTPException(404, f"no scan #{scan_id}")
    job_id = _start_job("report", f"report for scan #{scan_id}",
                        lambda: _do_report(scan_id))
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}", dependencies=[Depends(_auth)])
def api_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return job


@app.get("/api/scans", dependencies=[Depends(_auth)])
def api_scans(limit: int = 50):
    con = store.connect()
    rows = con.execute(
        "SELECT id, created_at, business, keyword, grid_size, radius_miles,"
        "       visibility, avg_rank, top3_pct, found_pct, dfs_cost"
        " FROM scans ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    cols = ["id", "created_at", "business", "keyword", "grid_size",
            "radius_miles", "visibility", "avg_rank", "top3_pct", "found_pct",
            "dfs_cost"]
    scans = [dict(zip(cols, row)) for row in rows]
    for s in scans:
        s["files"] = _scan_files(s["business"], s["id"])
    return scans


# ---------------------------------------------------------------- ui

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>gridscout</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --bg:#0a0e14; --panel:#111722; --line:#1e2836; --text:#d7e1ec;
          --dim:#7d8aa0; --cyan:#00e5ff; --purple:#a855f7; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:14px/1.5 "IBM Plex Mono", ui-monospace, Menlo, monospace; }
  .wrap { max-width:1080px; margin:0 auto; padding:32px 20px; }
  h1 { font-size:20px; letter-spacing:.12em; margin:0 0 4px; }
  h1 b { color:var(--cyan); font-weight:700; }
  .tag { color:var(--dim); margin:0 0 28px; }
  form, .panel { background:var(--panel); border:1px solid var(--line);
                 border-radius:8px; padding:20px; margin-bottom:24px; }
  label { display:block; color:var(--dim); font-size:12px; margin:10px 0 3px;
          text-transform:uppercase; letter-spacing:.08em; }
  input { width:100%; background:var(--bg); border:1px solid var(--line);
          border-radius:5px; color:var(--text); padding:8px 10px;
          font:inherit; }
  input:focus { outline:none; border-color:var(--cyan); }
  .row { display:flex; gap:14px; } .row > div { flex:1; }
  button { background:var(--cyan); color:#00222a; border:0; border-radius:5px;
           padding:10px 22px; margin-top:16px; font:inherit; font-weight:700;
           cursor:pointer; }
  button.ghost { background:transparent; color:var(--cyan);
                 border:1px solid var(--cyan); padding:3px 10px; margin:0;
                 font-weight:400; font-size:12px; }
  button:disabled { opacity:.5; cursor:default; }
  #status { white-space:pre-wrap; color:var(--dim); min-height:1.5em; }
  #status .ok { color:var(--cyan); } #status .err { color:#ff5470; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:7px 10px;
           border-bottom:1px solid var(--line); }
  th { color:var(--purple); font-size:11px; text-transform:uppercase;
       letter-spacing:.08em; }
  td a { color:var(--cyan); text-decoration:none; margin-right:10px; }
  .num { text-align:right; } th.num { text-align:right; }
</style></head><body><div class="wrap">
<h1><b>grid</b>scout</h1>
<p class="tag">where they rank, where they are invisible</p>

<form id="f">
  <div class="row">
    <div><label>business name (as on Google Maps)</label>
      <input name="business" required placeholder="Avalon Laser"></div>
    <div><label>keyword customers type</label>
      <input name="keyword" required placeholder="laser hair removal"></div>
  </div>
  <label>street address (geocoded for you)</label>
  <input name="address" required placeholder="2445 Fifth Ave, San Diego, CA 92103">
  <div class="row">
    <div><label>grid size</label><input name="size" value="7"></div>
    <div><label>radius, miles</label><input name="radius" value="2"></div>
  </div>
  <button id="go">scan</button>
  <div id="status"></div>
</form>

<div class="panel"><table id="scans"><thead><tr>
  <th>#</th><th>business</th><th>keyword</th><th class="num">visible</th>
  <th class="num">avg rank</th><th class="num">top 3</th><th>files</th><th></th>
</tr></thead><tbody></tbody></table></div>

<script>
const $ = s => document.querySelector(s);
const status = (msg, cls) =>
  $('#status').innerHTML = cls ? `<span class="${cls}">${msg}</span>` : msg;

async function poll(jobId, onDone) {
  const r = await fetch('/api/jobs/' + jobId);
  const j = await r.json();
  if (j.status === 'running') return setTimeout(() => poll(jobId, onDone), 3000);
  onDone(j);
}

async function loadScans() {
  const scans = await (await fetch('/api/scans')).json();
  $('#scans tbody').innerHTML = scans.map(s => `<tr>
    <td>${s.id}</td><td>${s.business}</td><td>${s.keyword}</td>
    <td class="num">${s.found_pct}%</td>
    <td class="num">${s.avg_rank ?? '-'}</td>
    <td class="num">${s.top3_pct}%</td>
    <td>${s.files.map ? `<a href="${s.files.map}" target="_blank">map</a>` : ''}
        ${s.files.report ? `<a href="${s.files.report}" target="_blank">pdf</a>` : ''}</td>
    <td>${s.files.report ? '' :
        `<button class="ghost" onclick="buildReport(${s.id}, this)">build report</button>`}</td>
  </tr>`).join('');
}

async function buildReport(id, btn) {
  btn.disabled = true; btn.textContent = 'building...';
  const r = await fetch('/api/report/' + id, {method: 'POST'});
  const j = await r.json();
  poll(j.job_id, res => {
    if (res.status === 'error') { btn.textContent = 'failed'; status(res.detail, 'err'); }
    else loadScans();
  });
}

$('#f').addEventListener('submit', async e => {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(e.target));
  d.size = +d.size; d.radius = +d.radius;
  $('#go').disabled = true;
  status('geocoding + scanning, a 7x7 runs about two minutes...');
  const r = await fetch('/api/scan', {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(d)});
  const j = await r.json();
  if (!r.ok) { status(j.detail || 'failed', 'err'); $('#go').disabled = false; return; }
  if (j.matched_address) status('scanning from: ' + j.matched_address);
  poll(j.job_id, res => {
    $('#go').disabled = false;
    if (res.status === 'error') return status(res.detail, 'err');
    const v = res.result;
    status(`scan #${v.scan_id} done. visible on ${v.found_pct}% of pins, ` +
           `avg rank ${v.avg_rank ?? '-'} where found. ` +
           `cost $${v.dfs_cost.toFixed(2)}.`, 'ok');
    loadScans();
  });
});

loadScans();
</script>
</div></body></html>"""


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def index():
    return PAGE


os.makedirs(OUT, exist_ok=True)
app.mount("/output", StaticFiles(directory=OUT), name="output")
