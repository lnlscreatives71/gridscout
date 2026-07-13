"""The findings file: everything the model is allowed to know, computed in Python.

This is the seam the whole AI layer turns on. Python does the arithmetic here and
writes it to a structured file. The model reads this file and writes prose from it.
The model never computes a rank, invents a competitor, or estimates a gap. If a
number appears in a report, it came from this file, which means every number is
auditable and the copy can always be rewritten by hand off the same data.

Every value here is calculated from the scan, not generated. Where a signal was
never pulled (a profile field a provider did not return), it is left null rather
than guessed, so the model can say "unknown" instead of inventing a figure.
"""
from . import geo


def _zone_place(zone, use_geo, cache):
    """Attach a real neighborhood name to a zone when a network is available."""
    if not use_geo:
        return zone["phrase"], None
    key = (round(zone["centroid_lat"], 4), round(zone["centroid_lng"], 4))
    if key not in cache:
        cache[key] = geo.reverse_details(zone["centroid_lat"], zone["centroid_lng"])
    details = cache[key]
    place = details.get("neighborhood") or zone["phrase"]
    return place, details.get("city")


def _competitor_public(c):
    """The subset of a competitor's profile safe and useful to hand the model."""
    return {
        "name": c["name"],
        "rating": c.get("rating"),
        "reviews": c.get("reviews"),
        "photos_count": c.get("photos_count"),
        "has_description": c.get("has_description"),
        "categories": c.get("categories") or [],
        "available_attributes": c.get("available_attributes") or [],
        "wins": c.get("wins"),
        "appearances": c.get("appearances"),
        "best_rank": c.get("best_rank"),
    }


def _reach(pins):
    """How far from the business it still shows up, in plain miles and directions.

    This is the number a business owner actually feels: not a score, but how many
    blocks out a searcher can be and still find them. It is directional, because
    competitors bend the edge in, and that asymmetry is the story.
    """
    found = [p for p in pins if p["rank"] is not None]
    gray = [p for p in pins if p["rank"] is None and p["sector"] != "center"]
    if not found:
        return None
    farthest = max(found, key=lambda p: p["dist_miles"])
    reach = {
        "farthest_you_appear_miles": round(farthest["dist_miles"], 1),
        "in_direction": farthest["sector"],
        "closest_you_vanish_miles": (round(min(p["dist_miles"] for p in gray), 1)
                                     if gray else None),
    }
    # farthest visible distance per compass direction, so the copy can say
    # "out to about 1.8 miles west but barely a mile east"
    by_dir = {}
    for p in found:
        d = p["sector"]
        if d == "center":
            continue
        by_dir[d] = max(by_dir.get(d, 0), round(p["dist_miles"], 1))
    reach["by_direction"] = by_dir
    if by_dir:
        reach["strongest_direction"] = max(by_dir, key=by_dir.get)
        reach["weakest_direction"] = min(by_dir, key=by_dir.get)
    return reach


def build(analysis, use_geo=True):
    """Turn the computed analysis into the findings dict handed to the model."""
    m = analysis["meta"]
    s = analysis["stats"]
    t = analysis["target"]
    g = analysis["gaps"]
    comp_by_name = {c["name"]: c for c in analysis["competitors"]}
    geo_cache = {}
    city = None

    def zone_out(z, weak):
        nonlocal city
        place, z_city = _zone_place(z, use_geo, geo_cache)
        city = city or z_city
        dom = comp_by_name.get(z["dominant"]) if z["dominant"] else None
        # rank delta: how far behind the pack leader the target sits in this zone.
        # The leader holds rank 1 at the pins it wins, so the delta is the target's
        # average rank there minus 1 (null where the target never appears).
        rank_delta = (round(z["avg_rank"] - 1, 1)
                      if z["avg_rank"] is not None else None)
        out = {
            "place": place,
            "direction": z["sector"],
            "ring": z["ring"],
            "pin_count": z["pin_count"],
            "avg_rank": z["avg_rank"],
            "rank_delta_vs_leader": rank_delta,
        }
        if weak:
            out["invisible_count"] = z["invisible_count"]
            out["dominant_competitor"] = _competitor_public(dom) if dom else None
        return out

    weak = [zone_out(z, True) for z in analysis["weak_zones"]]
    strong = [zone_out(z, False) for z in analysis["strong_zones"]]

    findings = {
        "business": m["business"],
        "keyword": m["keyword"],
        "city": city,
        "provider": m["provider"],
        "scanned_at": m.get("created_at"),
        "grid": {
            "size": m["grid_size"],
            "radius_miles": m["radius_miles"],
            "center_lat": m["center_lat"],
            "center_lng": m["center_lng"],
            "points": s["n"],
        },
        "reach": _reach(analysis["pins"]),
        "visibility": {
            "score": s["visibility"],
            "avg_rank_where_found": s["avg_rank"],
            "pct_top3": s["top3_pct"],
            "pct_visible": s["found_pct"],
            "pct_invisible": s["invisible_pct"],
            "points_visible": s["found"],
            "points_invisible": s["invisible"],
        },
        "target_profile": {
            "name": t["name"],
            "rating": t.get("rating"),
            "reviews": t.get("reviews"),
            "photos_count": t.get("photos_count"),
            "claimed": t.get("claimed"),
            "has_description": t.get("has_description"),
            "categories": t.get("categories") or [],
            "available_attributes": t.get("available_attributes") or [],
            "unavailable_attributes": t.get("unavailable_attributes") or [],
        },
        "strong_zones": strong,
        "weak_zones": weak,
        "top_competitors": [_competitor_public(c)
                            for c in analysis["competitors"][:6]],
        "gaps_vs_weak_zone_leader": {
            "leader": g["leader"]["name"] if g.get("leader") else None,
            "review_count_gap": g.get("reviews_gap"),
            "rating_gap": g.get("rating_gap"),
            "photo_count_gap": g.get("photo_gap"),
            "categories_leader_has_that_you_lack": g.get("missing_categories") or [],
            "attributes_leader_lists_that_you_lack": g.get("missing_attributes") or [],
            "you_have_a_business_description": g.get("target_has_description"),
            "leader_has_a_business_description": g.get("leader_has_description"),
            "you_are_claimed": g.get("target_claimed"),
        },
        # a standing reminder of the one thing the copy must never get wrong
        "honesty_constraint": (
            "Proximity dominates the local pack. A single location cannot rank "
            "first everywhere. Content and profile work push relevance and "
            "prominence, which stretches the visible radius at the margins. That "
            "is the only promise the copy may make."
        ),
    }
    return findings
