"""Assembles the content folder. The model writes the prose (pages and posts);
Python writes the data (the LocalBusiness JSON-LD and the competitor gap sheet,
both computed straight from the findings). Publishes nothing.

Keeping schema and the gap sheet in Python is the same discipline as everywhere
else in this tool: numbers and structured data are calculated, never generated.
"""
import json
import os

_ACRONYMS = {"hvac", "ac", "hoa", "llc", "suv", "hd", "led", "hp", "usa"}


def _title(s):
    out = []
    for w in s.split():
        if w.lower() in _ACRONYMS:
            out.append(w.upper())
        elif w.isupper():
            out.append(w)
        else:
            out.append(w.capitalize())
    return " ".join(out)


def _slugify(text):
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def _json_ld(findings):
    """LocalBusiness schema whose areaServed lists exactly the weak zones."""
    t = findings["target_profile"]
    grid = findings["grid"]
    area = [z["place"] for z in findings["weak_zones"]]
    data = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": findings["business"],
        "description": f"{_title(findings['keyword'])} serving the area around the "
                       f"business, including the neighborhoods it is working to reach.",
        "geo": {
            "@type": "GeoCoordinates",
            "latitude": grid["center_lat"],
            "longitude": grid["center_lng"],
        },
        "areaServed": [{"@type": "Place", "name": name} for name in area],
    }
    if t.get("rating") and t.get("reviews"):
        data["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": t["rating"],
            "reviewCount": t["reviews"],
        }
    if t.get("categories"):
        data["knowsAbout"] = t["categories"]
    return json.dumps(data, indent=2)


def _gap_sheet(findings):
    t = findings["target_profile"]
    g = findings["gaps_vs_weak_zone_leader"]
    L = ["# Competitor gap", "",
         "Pulled straight from the scan. These are the closable differences between "
         "you and the businesses winning the zones where you are invisible. Closing "
         "them lifts relevance and prominence, which widens your radius. It does not "
         "beat distance, so treat it as extending your reach, not blanketing the map.",
         "",
         f"You: {t.get('reviews','?')} reviews, {t.get('rating','?')} stars, "
         f"{t.get('photos_count','?')} photos, "
         f"description {'present' if t.get('has_description') else 'missing'}.",
         ""]
    if g.get("leader"):
        L.append(f"Leader in your weak zones: {g['leader']}")
        L.append("")
    def line(label, val, suffix=""):
        if val is not None:
            L.append(f"- {label}: {val}{suffix}")
    line("Reviews behind the leader", g.get("review_count_gap"))
    line("Rating behind the leader", g.get("rating_gap"), " stars")
    line("Photos behind the leader", g.get("photo_count_gap"))
    if g.get("categories_leader_has_that_you_lack"):
        L.append(f"- Categories the leader lists that you do not: "
                 f"{', '.join(g['categories_leader_has_that_you_lack'])}")
    if g.get("attributes_leader_lists_that_you_lack"):
        L.append(f"- Profile attributes the leader lists that you do not: "
                 f"{', '.join(g['attributes_leader_lists_that_you_lack'])}")
    if g.get("leader_has_a_business_description") and not g.get(
            "you_have_a_business_description"):
        L.append("- The leader has a business description on its profile and you "
                 "do not.")
    return "\n".join(L)


def assemble(findings, drafts, out_dir):
    """Write model drafts plus deterministic schema and gap sheet. Returns paths."""
    os.makedirs(out_dir, exist_ok=True)
    pages_dir = os.path.join(out_dir, "service-area-pages")
    os.makedirs(pages_dir, exist_ok=True)
    # clear stale drafts from a previous run so a refresh leaves a clean set and
    # never mixes old copy in with new
    for old in os.listdir(pages_dir):
        if old.endswith(".md"):
            os.remove(os.path.join(pages_dir, old))
    written = []

    for page in drafts.get("pages", []):
        place = page.get("place", "area")
        slug = page.get("slug") or _slugify(place)
        path = os.path.join(pages_dir, f"service-{slug}.md")
        with open(path, "w") as f:
            f.write((page.get("markdown") or "").rstrip() + "\n")
        written.append(path)

    posts = drafts.get("posts", [])
    if posts:
        path = os.path.join(out_dir, "gbp-posts.md")
        with open(path, "w") as f:
            f.write(f"# GBP post drafts for {findings['business']}\n\n"
                    "Geo-referenced to your weak zones. Post on a rotation, not all "
                    "at once.\n\n")
            for p in posts:
                f.write(f"## Post for {p.get('place','')}\n\n"
                        f"{(p.get('text') or '').strip()}\n\n")
        written.append(path)

    ld_path = os.path.join(out_dir, "localbusiness.jsonld")
    with open(ld_path, "w") as f:
        f.write(_json_ld(findings) + "\n")
    written.append(ld_path)

    gap_path = os.path.join(out_dir, "competitor-gap.md")
    with open(gap_path, "w") as f:
        f.write(_gap_sheet(findings) + "\n")
    written.append(gap_path)

    return written
