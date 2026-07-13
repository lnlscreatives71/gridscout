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
            out.append({
                "rank": rank,
                "name": it.get("title"),
                "place_id": it.get("place_id"),
                "rating": (it.get("rating") or {}).get("value"),
                "reviews": (it.get("rating") or {}).get("votes_count"),
                "category": it.get("category"),
            })
            if rank >= depth:
                break
        return out
