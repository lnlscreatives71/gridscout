"""SQLite store. Every scan is persisted, which is what makes ranking history free."""
import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.getenv("GRIDSCOUT_DB", os.path.expanduser("~/.gridscout/gridscout.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    business TEXT NOT NULL,
    keyword TEXT NOT NULL,
    center_lat REAL NOT NULL,
    center_lng REAL NOT NULL,
    grid_size INTEGER NOT NULL,
    radius_miles REAL NOT NULL,
    provider TEXT NOT NULL,
    avg_rank REAL,
    visibility REAL,
    top3_pct REAL,
    found_pct REAL,
    dfs_cost REAL DEFAULT 0,
    target_profile_json TEXT
);
CREATE TABLE IF NOT EXISTS pins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    row INTEGER, col INTEGER,
    lat REAL, lng REAL,
    dist_miles REAL,
    rank INTEGER,            -- NULL = not found in depth
    results_json TEXT        -- full local pack at this pin
);
CREATE INDEX IF NOT EXISTS idx_pins_scan ON pins(scan_id);

-- Model output cached alongside the scan so re-running report (or content)
-- does not re-bill the API. kind is 'analysis' | 'content'. Cost fields are
-- the real spend of the call that produced this row.
CREATE TABLE IF NOT EXISTS ai_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    model TEXT,
    content TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost REAL,
    created_at TEXT NOT NULL,
    UNIQUE(scan_id, kind)
);
"""


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def _migrate(con):
    """Add columns that may be missing from a database created by an older build."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(scans)").fetchall()}
    if "dfs_cost" not in cols:
        con.execute("ALTER TABLE scans ADD COLUMN dfs_cost REAL DEFAULT 0")
    if "target_profile_json" not in cols:
        con.execute("ALTER TABLE scans ADD COLUMN target_profile_json TEXT")
    con.commit()


def save_scan(con, meta: dict, pins: list[dict]) -> int:
    cur = con.execute(
        """INSERT INTO scans (created_at, business, keyword, center_lat, center_lng,
           grid_size, radius_miles, provider, avg_rank, visibility, top3_pct,
           found_pct, dfs_cost, target_profile_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            meta["business"], meta["keyword"], meta["center_lat"], meta["center_lng"],
            meta["grid_size"], meta["radius_miles"], meta["provider"],
            meta["avg_rank"], meta["visibility"], meta["top3_pct"], meta["found_pct"],
            meta.get("dfs_cost", 0.0),
            json.dumps(meta["target_profile"]) if meta.get("target_profile") else None,
        ),
    )
    scan_id = cur.lastrowid
    con.executemany(
        """INSERT INTO pins (scan_id, row, col, lat, lng, dist_miles, rank, results_json)
           VALUES (?,?,?,?,?,?,?,?)""",
        [
            (scan_id, p["row"], p["col"], p["lat"], p["lng"], p["dist_miles"],
             p["rank"], json.dumps(p["results"]))
            for p in pins
        ],
    )
    con.commit()
    return scan_id


def get_scan(con, scan_id: int):
    scan = con.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
    if not scan:
        raise SystemExit(f"no scan with id {scan_id}")
    pins = con.execute(
        "SELECT * FROM pins WHERE scan_id=? ORDER BY row, col", (scan_id,)
    ).fetchall()
    return scan, pins


def latest_scan_id(con, business: str | None = None):
    if business:
        r = con.execute(
            "SELECT id FROM scans WHERE business=? ORDER BY id DESC LIMIT 1", (business,)
        ).fetchone()
    else:
        r = con.execute("SELECT id FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    return r["id"] if r else None


def save_ai_output(con, scan_id: int, kind: str, model: str, content: str,
                   input_tokens: int, output_tokens: int, cost: float):
    con.execute(
        """INSERT INTO ai_outputs
           (scan_id, kind, model, content, input_tokens, output_tokens, cost, created_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(scan_id, kind) DO UPDATE SET
             model=excluded.model, content=excluded.content,
             input_tokens=excluded.input_tokens, output_tokens=excluded.output_tokens,
             cost=excluded.cost, created_at=excluded.created_at""",
        (scan_id, kind, model, content, input_tokens, output_tokens, cost,
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    con.commit()


def get_ai_output(con, scan_id: int, kind: str):
    return con.execute(
        "SELECT * FROM ai_outputs WHERE scan_id=? AND kind=?", (scan_id, kind)
    ).fetchone()


def history(con, business: str, keyword: str):
    return con.execute(
        """SELECT id, created_at, avg_rank, visibility, top3_pct, found_pct
           FROM scans WHERE business=? AND keyword=? ORDER BY created_at""",
        (business, keyword),
    ).fetchall()
