"""Provider adapters. Swap data vendors without touching the rest of the app.

Every provider implements:
    search(keyword, lat, lng, depth) -> list[dict]
where each dict is a local result:
    {"rank": int, "name": str, "place_id": str|None, "rating": float|None,
     "reviews": int|None, "category": str|None}

Set GRIDSCOUT_PROVIDER=mock|dataforseo (default: mock).
"""
import os


def get_provider(name: str | None = None):
    name = (name or os.getenv("GRIDSCOUT_PROVIDER") or "mock").lower()
    if name == "mock":
        from .mock import MockProvider
        return MockProvider()
    if name == "dataforseo":
        from .dataforseo import DataForSEOProvider
        return DataForSEOProvider()
    raise ValueError(f"unknown provider: {name}")
