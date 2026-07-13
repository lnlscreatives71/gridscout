"""The AI Ranking Coach. Renders the analysis structure as written, readable
analysis a business owner can act on. Real reasoning over the scan, in geographic
and competitive language, held to one rule above all: it never promises that a
page or a profile can beat physical distance. It promises a wider radius, which is
the thing those levers actually deliver.
"""
from . import analysis


def _plain_list(items):
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def render(a) -> str:
    m = a["meta"]
    s = a["stats"]
    t = a["target"]
    g = a["gaps"]
    L = []
    w = L.append

    w(f"RANKING ANALYSIS")
    w(f"{m['business']}  |  \"{m['keyword']}\"")
    w(f"{m['grid_size']}x{m['grid_size']} grid, {m['radius_miles']} mi radius, "
      f"scanned {m.get('created_at','')} via {m['provider']}")
    w("")
    w("=" * 68)
    w("")

    # 1. The shape of the map
    strong = _plain_list([z["sector"] for z in a["strong_zones"]]) or "a small core"
    w("WHERE YOU STAND")
    w("")
    if s["found_pct"] >= 99 and s["invisible"] == 0:
        w(f"You appear somewhere in the pack at every point scanned, averaging "
          f"rank {s['avg_rank']}. You are strongest around {strong}.")
    else:
        w(f"You are visible at {s['found_pct']}% of the {s['n']} points scanned and "
          f"invisible at {s['invisible']} of them. Where you do show up, your "
          f"average position is {s['avg_rank']}. Your visibility score is "
          f"{s['visibility']} out of 100.")
    w("")
    if a["strong_zones"]:
        w(f"Your strength is concentrated in {strong}. That is exactly what "
          f"proximity predicts: you rank best on the ground closest to your "
          f"location and fall away from there.")
    if a["weak_zones"]:
        weak_phrases = _plain_list([z["phrase"] for z in a["weak_zones"][:4]])
        w(f"You go weak, and in places disappear entirely, across {weak_phrases}. "
          f"Those are the blocks where a searcher does not see you at all.")
    w("")

    # 2. Who is taking the ground
    w("WHO IS WINNING THE GROUND YOU ARE LOSING")
    w("")
    named = []
    for z in a["weak_zones"][:5]:
        if z["dominant"]:
            named.append(f"  {z['phrase'].capitalize()}: {z['dominant']} holds the "
                         f"top spot there.")
    if named:
        w("The pin-by-pin winners in your weak zones are not random. A few "
          "businesses own them:")
        w("")
        L.extend(named)
        w("")
    if g["leader"]:
        ld = g["leader"]
        w(f"The one taking the most of your losing ground is {ld['name']}, "
          f"carrying about {ld.get('reviews', 0)} reviews at "
          f"{ld.get('rating','?')} stars.")
        w("")

    # 3. Why
    w("WHY THEY WIN THERE")
    w("")
    reasons = []
    if g.get("reviews_gap") and g["reviews_gap"] > 0:
        reasons.append(
            f"a review-count gap of about {g['reviews_gap']} in their favor "
            f"({g['target_reviews']} for you against roughly "
            f"{(g['leader'] or {}).get('reviews', 0)} for them)")
    if g.get("rating_gap") and g["rating_gap"] > 0.1:
        reasons.append(
            f"a rating edge of {g['rating_gap']} stars "
            f"({g['target_rating']} against {(g['leader'] or {}).get('rating')})")
    if g.get("missing_categories"):
        reasons.append(
            f"category coverage you do not match: "
            f"{_plain_list(g['missing_categories'])}")
    if reasons:
        w(f"Part of it is pure distance: their shops sit closer to those blocks "
          f"than yours does, and distance is the heaviest factor in the pack. But "
          f"distance is not the whole story here. They also carry "
          f"{_plain_list(reasons)}. Those are prominence and relevance signals, and "
          f"unlike distance, they are ones you can move.")
    else:
        w("In these zones the gap is mostly distance. Their locations sit closer to "
          "those blocks than yours, and proximity is the heaviest factor in the "
          "local pack. Your profile is broadly competitive with theirs, which means "
          "the honest lever here is reach, not a profile fix.")
    w("")

    # 4. What to do
    w("WHAT TO DO, IN ORDER OF LEVERAGE")
    w("")
    for i, r in enumerate(a["recommendations"], 1):
        tag = {"high": "highest leverage", "medium": "worth doing",
               "context": "the honest ceiling"}.get(r["leverage"], r["leverage"])
        w(f"{i}. {r['title']}  ({tag})")
        w(f"   {r['detail']}")
        w("")

    return "\n".join(L)
