"""DataForSEO Google Maps provider.

Auth: HTTP basic, login + password (not a bearer token).
Env:  DFS_LOGIN, DFS_PASSWORD

Uses the live/advanced Google Maps endpoint so a scan is one round trip per pin.
The `location_coordinate` param is "lat,lng,zoom" - zoom is required and pins the
search to that exact point, which is the whole trick this tool depends on.

If DataForSEO changes its schema, this is the only file that has to change.
"""
import base64
import json
import os
import urllib.request

ENDPOINT = "https://api.dataforseo.com/v3/serp/google/maps/live/advanced"
BUSINESS_INFO = "https://api.dataforseo.com/v3/business_data/google/my_business_info/live"


def _humanize(key):
    """Turn a machine attribute key into readable text, e.g.
    'onsite_services' -> 'Onsite services', 'has_seating_outdoors' -> 'Seating
    outdoors', 'identifies_as_veteran_owned' -> 'Veteran owned'."""
    s = str(key).replace("_", " ").strip()
    for p in ("identifies as ", "has ", "is "):
        if s.startswith(p):
            s = s[len(p):]
            break
    return s[:1].upper() + s[1:] if s else s


def _flatten_attrs(attributes, available: bool):
    """Pull attribute names out of DataForSEO's attributes block.

    Both the Maps result and the Business Data profile group attributes under
    `available_attributes` and `unavailable_attributes`, each a dict of
    category -> list of machine keys. Flatten and humanize. Returns an empty list
    when the field is absent so the findings layer can tell "none listed" from
    "not pulled".
    """
    if not isinstance(attributes, dict):
        return []
    key = "available_attributes" if available else "unavailable_attributes"
    block = attributes.get(key) or {}
    names = []
    if isinstance(block, dict):
        for group in block.values():
            if isinstance(group, list):
                names.extend(_humanize(n) for n in group)
    return names


class DataForSEOProvider:
    name = "dataforseo"

    def __init__(self, login: str | None = None, password: str | None = None):
        self.login = login or os.getenv("DFS_LOGIN")
        self.password = password or os.getenv("DFS_PASSWORD")
        if not self.login or not self.password:
            raise RuntimeError(
                "DataForSEO credentials missing. Set DFS_LOGIN and DFS_PASSWORD, "
                "or run with --provider mock."
            )
        token = base64.b64encode(f"{self.login}:{self.password}".encode()).decode()
        self.auth_header = f"Basic {token}"
        # Running tally of what this scan actually cost, read straight from the
        # API responses so the spend line at the end of a run is real, not an
        # estimate. The scanner reads this after all pins are queried.
        self.total_cost = 0.0

    def search(self, keyword: str, lat: float, lng: float, depth: int = 20):
        payload = [{
            "keyword": keyword,
            "language_code": "en",
            "location_coordinate": f"{lat},{lng},15z",
            "depth": depth,
        }]
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": self.auth_header,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())

        # DataForSEO reports the exact cost of the call. Track it so spend is real.
        try:
            self.total_cost += float(data.get("cost") or 0.0)
        except (TypeError, ValueError):
            pass

        try:
            items = data["tasks"][0]["result"][0]["items"] or []
        except (KeyError, IndexError, TypeError):
            return []

        out = []
        rank = 0
        for it in items:
            if it.get("type") != "maps_search":
                continue
            rank += 1
            # The Maps live endpoint carries some profile signal directly. Deeper
            # fields (full attribute lists, photo counts) come from a Business Data
            # profile pull, which is left as None here rather than guessed. The
            # findings layer treats missing fields as unknown, never as zero.
            out.append({
                "rank": rank,
                "name": it.get("title"),
                "place_id": it.get("place_id"),
                "cid": it.get("cid"),
                "rating": (it.get("rating") or {}).get("value"),
                "reviews": (it.get("rating") or {}).get("votes_count"),
                "category": it.get("category"),
                "additional_categories": it.get("additional_categories") or [],
                "photos_count": it.get("total_photos"),
                "claimed": it.get("is_claimed"),
                # the maps result's "snippet" is the address, not a business
                # description. The real description comes from the Business Data
                # deep pull, so leave it None here rather than mislabel the address.
                "description": None,
                "available_attributes": _flatten_attrs(it.get("attributes"), True),
                "unavailable_attributes": _flatten_attrs(it.get("attributes"), False),
            })
            if rank >= depth:
                break
        return out

    def business_info(self, cid=None, keyword=None, lat=None, lng=None):
        """Deep Google Business Profile pull for one business.

        Prefer the cid (the business's Google id, carried on the maps result) for
        an exact match. Falls back to a name plus coordinate search. Returns the
        full profile (real description, attributes, services, photos, claimed) or
        None. About half a cent per call.
        """
        body = {"language_code": "en"}
        if cid:
            body["keyword"] = f"cid:{cid}"
        elif keyword:
            body["keyword"] = keyword
        else:
            return None
        if lat is not None and lng is not None:
            body["location_coordinate"] = f"{lat},{lng}"
        elif not cid:
            return None

        req = urllib.request.Request(
            BUSINESS_INFO, data=json.dumps([body]).encode(),
            headers={"Authorization": self.auth_header,
                     "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            return None

        try:
            self.total_cost += float(data.get("cost") or 0.0)
        except (TypeError, ValueError):
            pass

        try:
            it = data["tasks"][0]["result"][0]["items"][0]
        except (KeyError, IndexError, TypeError):
            return None

        r = it.get("rating") or {}
        attrs = it.get("attributes") or {}
        return {
            "name": it.get("title"),
            "place_id": it.get("place_id"),
            "cid": it.get("cid"),
            "rating": r.get("value"),
            "reviews": r.get("votes_count"),
            "category": it.get("category"),
            "additional_categories": it.get("additional_categories") or [],
            "photos_count": it.get("total_photos"),
            "claimed": it.get("is_claimed"),
            "description": it.get("description"),
            "available_attributes": _flatten_attrs(attrs, True),
            "unavailable_attributes": _flatten_attrs(attrs, False),
            "services": it.get("services") or [],
            "url": it.get("url") or (
                f"http://{it['domain']}" if it.get("domain") else None),
            "phone": it.get("phone"),
        }
