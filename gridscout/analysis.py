"""The analytical core shared by analyze, content, and report.

This is where the reasoning lives. Given a saved scan, it works out where the
business owns the map and where it is invisible, who is winning the ground it is
losing, what specifically separates them, and what to do about it, ranked by
leverage. Everything downstream is presentation over this one structure.

It reasons in geographic and competitive terms, not row and column numbers, and it
is built to stay honest: proximity dominates the local pack, so the recommendations
talk about stretching a visible radius, never about lighting up an entire city.
"""
import json
from collections import Counter, defaultdict

from . import geo
from .scanner import _match

# A pin counts as "weak" if the target is below this rank or missing entirely.
# Position 10 is roughly the point where a business stops getting meaningful
# consideration in the local pack at that spot.
WEAK_RANK = 10
STRONG_RANK = 3


def _target_profile(business, pins):
    """Pull the target's own listing (rating, reviews, categories) out of the scan.

    The profile is the same wherever the business appears, so we take the richest
    sighting: the one reporting the most reviews.
    """
    best = None
    cats = Counter()
    for p in pins:
        for r in p["results"]:
            if _match(business, r.get("name", "")):
                if r.get("category"):
                    cats[r["category"]] += 1
                votes = r.get("reviews") or 0
                if best is None or votes > (best.get("reviews") or 0):
                    best = r
    prof = {
        "name": business,
        "rating": (best or {}).get("rating"),
        "reviews": (best or {}).get("reviews"),
        "place_id": (best or {}).get("place_id"),
        "categories": [c for c, _ in cats.most_common()],
    }
    return prof


def _competitor_table(pins):
    """Aggregate every business that appeared anywhere, with its profile and reach."""
    agg = {}
    for p in pins:
        for r in p["results"]:
            name = r.get("name")
            if not name:
                continue
            a = agg.setdefault(name, {
                "name": name, "rating": r.get("rating"),
                "reviews": r.get("reviews") or 0,
                "category": r.get("category"),
                "appearances": 0, "wins": 0,
                "ranks": [],
            })
            a["appearances"] += 1
            a["ranks"].append(r["rank"])
            if r["rank"] == 1:
                a["wins"] += 1
            # keep the strongest profile seen
            if (r.get("reviews") or 0) > a["reviews"]:
                a["reviews"] = r.get("reviews") or 0
            if r.get("rating") and (not a["rating"] or r["rating"] > a["rating"]):
                a["rating"] = r["rating"]
    for a in agg.values():
        a["best_rank"] = min(a["ranks"])
        a["avg_rank"] = round(sum(a["ranks"]) / len(a["ranks"]), 1)
    # influence = how much of the map they win, then how widely they appear
    return sorted(agg.values(), key=lambda a: (-a["wins"], -a["appearances"],
                                               a["avg_rank"]))


def _enrich_pins(meta, pins):
    clat, clng = meta["center_lat"], meta["center_lng"]
    radius = meta["radius_miles"]
    for p in pins:
        p["sector"] = geo.sector(clat, clng, p["lat"], p["lng"], p["dist_miles"])
        p["ring"] = geo.ring(p["dist_miles"], radius)
        p["winner"] = p["results"][0]["name"] if p["results"] else None
    return pins


def _zone(sector_name, pins_in_zone, invisible_only=False):
    ranks = [p["rank"] for p in pins_in_zone if p["rank"] is not None]
    invisible = sum(1 for p in pins_in_zone if p["rank"] is None)
    # who wins the ground we are losing: most frequent rank-1 holder here
    winners = Counter(p["winner"] for p in pins_in_zone if p["winner"])
    dominant = winners.most_common(1)[0][0] if winners else None
    dom_wins = winners.most_common(1)[0][1] if winners else 0
    # representative ring for the zone
    rings = Counter(p["ring"] for p in pins_in_zone)
    ring_name = rings.most_common(1)[0][0]
    # centroid, for later reverse geocoding
    clat = sum(p["lat"] for p in pins_in_zone) / len(pins_in_zone)
    clng = sum(p["lng"] for p in pins_in_zone) / len(pins_in_zone)
    return {
        "sector": sector_name,
        "ring": ring_name,
        "phrase": geo.zone_phrase(sector_name, ring_name),
        "short": geo.sector_short(sector_name),
        "pin_count": len(pins_in_zone),
        "invisible_count": invisible,
        "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
        "dominant": dominant,
        "dominant_wins": dom_wins,
        "centroid_lat": round(clat, 6),
        "centroid_lng": round(clng, 6),
    }


def compute(meta, pins):
    """Return the full analysis structure for a scan."""
    pins = _enrich_pins(meta, pins)
    n = len(pins)
    found = [p["rank"] for p in pins if p["rank"] is not None]
    invisible = n - len(found)

    target = _target_profile(meta["business"], pins)
    competitors = _competitor_table(pins)
    comp_by_name = {c["name"]: c for c in competitors}

    # group pins by compass sector, then judge each sector
    by_sector = defaultdict(list)
    for p in pins:
        by_sector[p["sector"]].append(p)

    weak_zones, strong_zones = [], []
    for sec, group in by_sector.items():
        weak_pins = [p for p in group if p["rank"] is None or p["rank"] > WEAK_RANK]
        strong_pins = [p for p in group
                       if p["rank"] is not None and p["rank"] <= STRONG_RANK]
        # a zone is weak if most of its pins are weak
        if len(weak_pins) >= max(2, len(group) * 0.5):
            weak_zones.append(_zone(sec, weak_pins))
        if len(strong_pins) >= max(1, len(group) * 0.5):
            strong_zones.append(_zone(sec, strong_pins))

    # worst zones first: most invisible, then worst average rank
    weak_zones.sort(key=lambda z: (-z["invisible_count"],
                                   -(z["avg_rank"] or 99)))
    strong_zones.sort(key=lambda z: (z["avg_rank"] or 99))

    gaps = _gaps(target, weak_zones, comp_by_name, competitors)
    recs = _recommendations(meta, target, gaps, weak_zones, strong_zones,
                            found, invisible, n)

    return {
        "meta": meta,
        "stats": {
            "n": n,
            "visibility": meta["visibility"],
            "avg_rank": meta["avg_rank"],
            "top3_pct": meta["top3_pct"],
            "found_pct": meta["found_pct"],
            "invisible_pct": round(invisible / n * 100, 1) if n else 0.0,
            "invisible": invisible,
            "found": len(found),
        },
        "target": target,
        "competitors": competitors,
        "pins": pins,
        "weak_zones": weak_zones,
        "strong_zones": strong_zones,
        "gaps": gaps,
        "recommendations": recs,
    }


def _gaps(target, weak_zones, comp_by_name, competitors):
    """What separates the target from the players winning its weak ground."""
    # the businesses actually winning the weak zones, ranked by how much of that
    # losing ground each one holds (sum of the pins they top across weak zones)
    ground = Counter()
    for z in weak_zones:
        if z["dominant"]:
            ground[z["dominant"]] += z["dominant_wins"]
    leaders = [comp_by_name[n] for n, _ in ground.most_common() if n in comp_by_name]
    if not leaders:
        leaders = competitors[:1]
    leader = leaders[0] if leaders else None

    t_reviews = target.get("reviews") or 0
    t_rating = target.get("rating")
    t_cats = set(c.lower() for c in target.get("categories", []))

    # categories the weak-zone winners carry that the target does not
    missing_cats = []
    for l in leaders:
        c = (l.get("category") or "").strip()
        if c and c.lower() not in t_cats and c not in missing_cats:
            missing_cats.append(c)

    reviews_gap = None
    rating_gap = None
    if leader:
        reviews_gap = (leader.get("reviews") or 0) - t_reviews
        if t_rating is not None and leader.get("rating") is not None:
            rating_gap = round(leader["rating"] - t_rating, 1)

    return {
        "leader": leader,
        "leaders": leaders,
        "reviews_gap": reviews_gap,
        "rating_gap": rating_gap,
        "missing_categories": missing_cats,
        "target_reviews": t_reviews,
        "target_rating": t_rating,
    }


def _recommendations(meta, target, gaps, weak_zones, strong_zones,
                     found, invisible, n):
    """Actions ranked by leverage, framed honestly around what actually moves rank."""
    recs = []
    leader = gaps.get("leader")

    # 1. Reviews. The single biggest prominence lever, and prominence is what
    #    stretches the visible radius outward at the margins.
    if leader and gaps.get("reviews_gap") and gaps["reviews_gap"] > 0:
        recs.append({
            "leverage": "high",
            "title": "Close the review-volume gap",
            "detail": (
                f"{leader['name']} carries about {leader.get('reviews', 0)} reviews "
                f"against your {gaps['target_reviews']}, and it is the business "
                f"holding the top spot across the zones where you disappear. Review "
                f"volume and recency are among the few prominence signals you control. "
                f"A steady inflow of recent, keyword-natural reviews is what widens the "
                f"radius you can hold. It will not carry you across the whole city, and "
                f"nothing will, but it moves the edge of your strong area outward."
            ),
        })

    # 2. Rating quality
    if gaps.get("rating_gap") and gaps["rating_gap"] > 0.1:
        recs.append({
            "leverage": "medium",
            "title": "Lift rating quality, not just count",
            "detail": (
                f"The leaders in your weak zones average about "
                f"{leader.get('rating')} stars to your {gaps['target_rating']}. A "
                f"half-star swing changes click behavior in the pack. Route recent "
                f"unhappy customers to a service recovery step before they rate, and "
                f"ask satisfied ones at the moment the job closes."
            ),
        })

    # 3. Categories / services surfaced by the winners
    if gaps.get("missing_categories"):
        cats = ", ".join(gaps["missing_categories"])
        recs.append({
            "leverage": "medium",
            "title": "Match the winners' category footprint",
            "detail": (
                f"Businesses beating you in the weak zones list categories you do "
                f"not: {cats}. Adding accurate primary and secondary categories on "
                f"your profile, and backing each with a real service page, tells "
                f"Google you are relevant for those searches. Relevance is the other "
                f"lever besides proximity, and it is fully in your hands."
            ),
        })

    # 4. Service-area pages for the specific weak neighborhoods
    if weak_zones:
        zone_list = ", ".join(z["phrase"] for z in weak_zones[:3])
        recs.append({
            "leverage": "medium",
            "title": "Build service-area pages for the dead zones",
            "detail": (
                f"You are weakest across {zone_list}. A genuine, locally specific "
                f"page for each, naming the streets, landmarks, and how people there "
                f"actually search, adds the relevance signal that lets you compete a "
                f"little further from home. Thin '[service] in [city]' pages do "
                f"nothing. Real local detail does."
            ),
        })

    # 5. The proximity reality check. Always present, always last, always honest.
    strong_dirs = ", ".join(z["sector"] for z in strong_zones[:3]) or "your core"
    recs.append({
        "leverage": "context",
        "title": "Set the right expectation on reach",
        "detail": (
            f"You currently own {strong_dirs} and hold roughly "
            f"{meta['found_pct']}% of the grid at some rank. Proximity is the "
            f"dominant factor in the local pack, so a single location cannot rank "
            f"first across an entire metro no matter how good the profile or the "
            f"pages are. The realistic goal is to push your strong radius outward and "
            f"to be visible, not necessarily first, further out. If the far zones "
            f"carry real revenue, the honest fix is a second location or a physical "
            f"presence closer to them, not more content."
        ),
    })
    return recs


# --- loading a scan back out of the store -------------------------------------

def load(con, store, scan_id):
    """Turn stored rows into the (meta, pins) shapes compute() expects."""
    scan, pin_rows = store.get_scan(con, scan_id)
    meta = {
        "scan_id": scan["id"],
        "created_at": scan["created_at"],
        "business": scan["business"],
        "keyword": scan["keyword"],
        "center_lat": scan["center_lat"],
        "center_lng": scan["center_lng"],
        "grid_size": scan["grid_size"],
        "radius_miles": scan["radius_miles"],
        "provider": scan["provider"],
        "avg_rank": scan["avg_rank"],
        "visibility": scan["visibility"],
        "top3_pct": scan["top3_pct"],
        "found_pct": scan["found_pct"],
    }
    pins = []
    for r in pin_rows:
        pins.append({
            "row": r["row"], "col": r["col"],
            "lat": r["lat"], "lng": r["lng"],
            "dist_miles": r["dist_miles"], "rank": r["rank"],
            "results": json.loads(r["results_json"]),
        })
    return meta, pins
