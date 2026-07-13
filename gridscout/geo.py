"""Geographic helpers: turn grid coordinates into human, directional language, and
optionally into real neighborhood names via OpenStreetMap.

Two jobs:

1. Directional description. A scan is a lattice, but nobody sells against "row 6,
   column 2." They understand "the north edge" and "the southwest corner." Every
   pin gets a compass sector and a distance ring so the analysis can speak in the
   terms a business owner actually thinks in.

2. Real place names, when a network is available. Reverse geocoding a weak zone's
   center against Nominatim (OSM, keyless) gives an actual neighborhood or suburb
   name to anchor a service-area page. It is rate limited, cached, and degrades to
   the directional description if offline or blocked, so nothing here is load
   bearing. No key, no account.
"""
import json
import math
import os
import time
import urllib.parse
import urllib.request

CACHE_PATH = os.path.expanduser("~/.gridscout/geocache.json")

# 8-way compass, clockwise from north. Index by round(bearing / 45).
_SECTORS = ["north", "northeast", "east", "southeast",
            "south", "southwest", "west", "northwest", "north"]
_SECTOR_SHORT = {"north": "N", "northeast": "NE", "east": "E", "southeast": "SE",
                 "south": "S", "southwest": "SW", "west": "W", "northwest": "NW",
                 "center": "C"}


def bearing(center_lat, center_lng, lat, lng):
    """Compass bearing in degrees from the center to a point, 0 = north."""
    dn = lat - center_lat
    de = (lng - center_lng) * math.cos(math.radians(center_lat))
    ang = math.degrees(math.atan2(de, dn))
    return (ang + 360) % 360


def sector(center_lat, center_lng, lat, lng, dist_miles, center_radius=0.6):
    """Return a compass sector name, or 'center' for pins near the middle."""
    if dist_miles <= center_radius:
        return "center"
    return _SECTORS[round(bearing(center_lat, center_lng, lat, lng) / 45.0)]


def sector_short(name):
    return _SECTOR_SHORT.get(name, name[:2].upper())


def ring(dist_miles, radius_miles):
    """Coarse distance band, relative to the scan radius."""
    if radius_miles <= 0:
        return "core"
    frac = dist_miles / radius_miles
    if frac <= 0.34:
        return "core"
    if frac <= 0.7:
        return "mid"
    return "edge"


def zone_phrase(sector_name, ring_name):
    """A readable phrase for a zone, e.g. 'the northwest edge' or 'the core'."""
    if sector_name == "center":
        return "the area right around the business"
    ring_word = {"core": "inner", "mid": "", "edge": "outer"}.get(ring_name, "")
    body = f"{sector_name} {ring_name}".strip()
    if ring_name == "edge":
        return f"the {sector_name} edge"
    if ring_name == "core":
        return f"the inner {sector_name} blocks"
    return f"the {sector_name} side"


# --- optional reverse geocoding ------------------------------------------------

def _load_cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    try:
        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except OSError:
        pass


def reverse_geocode(lat, lng, timeout=8):
    """Best-effort neighborhood/suburb/town name for a coordinate, or None.

    Uses OpenStreetMap's Nominatim, which is keyless. Cached on disk and rate
    limited to respect their usage policy. Returns None on any failure so callers
    can fall back to a directional description.
    """
    key = f"{lat:.4f},{lng:.4f}"
    cache = _load_cache()
    if key in cache:
        return cache[key] or None

    params = urllib.parse.urlencode({
        "lat": f"{lat:.6f}", "lon": f"{lng:.6f}", "format": "jsonv2",
        "zoom": "14", "addressdetails": "1",
    })
    url = f"https://nominatim.openstreetmap.org/reverse?{params}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "gridscout/1.0 (local SEO grid tool)",
    })
    name = None
    try:
        time.sleep(1.0)  # Nominatim asks for <= 1 request per second
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        addr = data.get("address", {}) or {}
        for field in ("neighbourhood", "suburb", "quarter", "city_district",
                      "hamlet", "village", "town", "borough"):
            if addr.get(field):
                name = addr[field]
                break
    except Exception:
        name = None

    cache[key] = name or ""
    _save_cache(cache)
    return name
