"""Content drafts for the weak zones. Generates, writes to a folder, publishes
nothing.

What it makes, per scan:

  - one service-area page per weak neighborhood, anchored to the real place name
    when a network is available, and written to compete a bit further from home
    rather than to promise blanket coverage
  - Google Business Profile post drafts, each pointed at a specific weak zone
  - LocalBusiness JSON-LD whose areaServed lists exactly the zones you are losing
  - a competitor gap section: what the winners carry on their profile that you do not

The copy is deliberately not "Best [service] in [city]" filler. It names the zone,
the corridor, the search phrasing people there actually use, and the specific
business currently holding that ground. Where only a human should supply a detail,
it leaves a clearly marked note rather than inventing a landmark.
"""
import json
import os

from . import geo


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


def _zone_place(zone, use_geo):
    """Resolve a zone to real address parts, falling back to directional language."""
    details = {}
    if use_geo:
        details = geo.reverse_details(zone["centroid_lat"], zone["centroid_lng"])
    label = details.get("neighborhood") or zone["phrase"]
    return label, details


def _service_area_page(meta, zone, gap_leader, label, details):
    kw = meta["keyword"]
    service = _title(kw)
    biz = meta["business"]
    city = details.get("city", "")
    road = details.get("road", "")
    place = label if label[0].isupper() else label

    corridor = f" along the {road} corridor" if road else ""
    city_line = f" in {city}" if city else ""
    rival = (f"Right now, {gap_leader['name']} tends to show up first for "
             f"\"{kw}\" searches out here. ") if gap_leader else ""

    lines = [
        f"# {service} near {place if place[0].isupper() else place.title()}",
        "",
        f"> Draft service-area page for {biz}. Review, add the local details only "
        f"you know where marked, then publish.",
        "",
        f"When something breaks{city_line}, you do not want to wait, and you do not "
        f"want a call center. {biz} covers {place}{corridor} and the streets around "
        f"it, and we answer the phone ourselves.",
        "",
        f"## Serving {place}",
        "",
        f"People near {place} usually search \"{kw}\" or \"{kw} near me\" the moment "
        f"the problem starts. {rival}We are a short drive away and we know this side "
        f"of town, so we can be on site while the search is still fresh.",
        "",
        f"<!-- ADD: two or three specific local anchors you actually know for "
        f"{place}. A landmark, a neighborhood name, a school or park, the kind of "
        f"homes here. Real detail is what makes this page rank. Do not invent it. -->",
        "",
        f"## Why homeowners near {place} call us",
        "",
        f"- We work {place} and the surrounding streets regularly, not as a "
        f"once-in-a-while trip",
        f"- Straight pricing before the work starts, no surprise line items",
        f"- {meta['business']} carries a "
        f"{meta.get('_target_rating','solid')}-star record across the area",
        "",
        f"## Book {kw} near {place}",
        "",
        f"Call or request a visit online. Tell us the cross street and we will give "
        f"you an honest arrival window for {place}.",
        "",
        f"<!-- HONEST NOTE: this page helps you compete a little further out toward "
        f"{place}. It will not by itself put you first there if a competitor sits "
        f"physically closer. Pair it with reviews and profile work. -->",
    ]
    return "\n".join(lines)


def _gbp_post(meta, zone, label):
    kw = meta["keyword"]
    place = label if label[0].isupper() else label.title()
    return (
        f"Heading out to {place} this week. If you searched \"{kw}\" near {place} "
        f"and had trouble finding someone close, that is us. {meta['business']} "
        f"covers {place} and the streets around it. Straight pricing, real arrival "
        f"windows, we answer our own phone. Book online or give us a call."
    )


def _json_ld(meta, weak_zones, target, area_labels):
    data = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": meta["business"],
        "description": f"{_title(meta['keyword'])} serving the wider area around "
                       f"the business, including the zones it is expanding into.",
        "geo": {
            "@type": "GeoCoordinates",
            "latitude": meta["center_lat"],
            "longitude": meta["center_lng"],
        },
        "areaServed": [{"@type": "Place", "name": name} for name in area_labels],
    }
    if target.get("rating") and target.get("reviews"):
        data["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": target["rating"],
            "reviewCount": target["reviews"],
        }
    if target.get("categories"):
        data["knowsAbout"] = target["categories"]
    return json.dumps(data, indent=2)


def _gap_section(a):
    g = a["gaps"]
    t = a["target"]
    lines = ["# Competitor gap", "",
             "What the businesses winning your weak zones carry that you do not, "
             "pulled straight from the scan. Close these and you close the "
             "relevance and prominence gap. You cannot close the distance gap, so "
             "treat this as widening your radius, not blanketing the map.", ""]
    lines.append(f"You: {t.get('reviews','?')} reviews, {t.get('rating','?')} "
                 f"stars, categories: {', '.join(t.get('categories') or ['unknown'])}")
    lines.append("")
    lines.append("Leaders in your weak zones:")
    lines.append("")
    seen = set()
    for z in a["weak_zones"]:
        name = z["dominant"]
        if not name or name in seen:
            continue
        seen.add(name)
        c = next((x for x in a["competitors"] if x["name"] == name), None)
        if not c:
            continue
        rev_gap = (c["reviews"] or 0) - (t.get("reviews") or 0)
        gap_note = f", {rev_gap} more reviews than you" if rev_gap > 0 else ""
        lines.append(f"- {name} wins {z['phrase']}: {c['reviews']} reviews, "
                     f"{c['rating']} stars{gap_note}")
    if g.get("missing_categories"):
        lines.append("")
        lines.append(f"Categories the winners list that you do not: "
                     f"{', '.join(g['missing_categories'])}")
    return "\n".join(lines)


def generate(a, out_dir, use_geo=True):
    """Write all drafts for a scan into out_dir. Returns a manifest of paths."""
    meta = dict(a["meta"])
    meta["_target_rating"] = a["target"].get("rating") or "solid"
    os.makedirs(out_dir, exist_ok=True)
    pages_dir = os.path.join(out_dir, "service-area-pages")
    os.makedirs(pages_dir, exist_ok=True)

    written = []
    area_labels = []
    posts = []
    gap_leader = a["gaps"].get("leader")

    # cap at the worst handful so this stays a focused deliverable
    for zone in a["weak_zones"][:5]:
        label, details = _zone_place(zone, use_geo)
        area_labels.append(label if label[0].isupper() else label.title())

        page = _service_area_page(meta, zone, gap_leader, label, details)
        fname = "service-" + "".join(
            c if c.isalnum() else "-" for c in label.lower()).strip("-") + ".md"
        path = os.path.join(pages_dir, fname)
        with open(path, "w") as f:
            f.write(page + "\n")
        written.append(path)

        posts.append(f"## Post for {label}\n\n{_gbp_post(meta, zone, label)}\n")

    # GBP posts
    posts_path = os.path.join(out_dir, "gbp-posts.md")
    with open(posts_path, "w") as f:
        f.write(f"# GBP post drafts for {meta['business']}\n\n"
                "Geo-referenced to your weak zones. One per zone. Post them on a "
                "rotation, not all at once.\n\n" + "\n".join(posts) + "\n")
    written.append(posts_path)

    # JSON-LD
    ld = _json_ld(meta, a["weak_zones"], a["target"], area_labels)
    ld_path = os.path.join(out_dir, "localbusiness.jsonld")
    with open(ld_path, "w") as f:
        f.write(ld + "\n")
    written.append(ld_path)

    # competitor gap
    gap_path = os.path.join(out_dir, "competitor-gap.md")
    with open(gap_path, "w") as f:
        f.write(_gap_section(a) + "\n")
    written.append(gap_path)

    return {"out_dir": out_dir, "files": written, "area_labels": area_labels}
