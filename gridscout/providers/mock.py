"""Mock provider. Simulates a real local pack so the whole pipeline runs with no key.

It models the thing that actually drives Maps rank: proximity, with prominence as
the modulator. Every business has a home coordinate and a prominence score. Rank at
a given pin is derived from distance-penalized prominence plus a little stable noise.

Two things make it useful rather than decorative:

1. It anchors the whole competitive set around the real scan center, so it produces
   a believable map for any city you point it at, not just one hardcoded town.
2. It injects the business name you actually typed as the target, sitting at the
   center with a moderate prominence. So the target dominates near its own location
   and fades out across town, which is the real, sellable local-pack story and the
   one the analysis layer needs weak zones to work with.
"""
import hashlib
import math
import random

# Named "hero" competitors: (name, home offset north mi, home offset east mi,
# prominence 0-100, category). These are the ones the analysis layer names as the
# businesses winning a given zone. A couple of strong players own their own lobes of
# the map and bury a moderate target out there. That asymmetry creates the dead
# zones worth analyzing.
COMPETITORS = [
    ("Summit Peak Services",       2.4,  2.6, 93, "HVAC contractor"),
    ("Cornerstone Comfort Co.",   -2.8, -2.2, 90, "HVAC contractor"),
    ("Ridgeline Heating & Air",   -2.1,  2.9, 84, "HVAC contractor"),
    ("Capital Mechanical Group",   3.0, -1.4, 80, "HVAC contractor"),
    ("Northgate Air Solutions",    1.2, -3.3, 76, "HVAC contractor"),
    ("Trueline Climate Control",  -3.4,  0.6, 72, "HVAC contractor"),
    ("Allied Furnace & Cooling",  -0.8, -3.7, 66, "Heating contractor"),
    ("Meridian Heating Services",  3.6,  3.1, 61, "HVAC contractor"),
    ("Old Town Air Company",      -3.9,  2.2, 55, "Heating contractor"),
    ("Prime Air & Refrigeration",  0.7,  4.0, 50, "HVAC contractor"),
    ("Ironwood Heating",           4.1, -3.0, 44, "HVAC contractor"),
]

# Where the target sits in the pack on its home turf. Moderate on purpose: strong
# enough to win the center, weak enough to lose the far corners to the big players.
TARGET_PROMINENCE = 71

# Profile attributes a Google Business Profile can carry. The strong players fill
# most of these in; the target has only a few. That difference is a real, closable
# gap the analysis can name, so it belongs in the simulated data.
GBP_ATTRIBUTES = [
    "Online estimates", "Onsite services", "24-hour emergency service",
    "Free consultation", "Financing available", "Wheelchair accessible entrance",
    "Veteran-owned", "Family-owned and operated", "Appointment required",
    "Repair services",
]


def _profile(name, prom, is_target, h):
    """Deterministic deep-profile fields for one business.

    Real ranking is not only proximity and reviews. Profile completeness, photo
    count, claimed status, and listed attributes all feed prominence. The mock
    fills these in so the findings file has genuine, calculable gaps to reason
    over. The target is deliberately given a thinner profile than the strong
    players, which is the common real situation: the business never finished
    filling its profile out.
    """
    seed = int(hashlib.md5(f"{name}{h[:4]}".encode()).hexdigest()[:8], 16)
    if is_target:
        n_attrs = 3
        photos = 11 + seed % 6
        described = False
        claimed = True
    else:
        n_attrs = min(len(GBP_ATTRIBUTES), 3 + round(prom / 100.0 * 6))
        photos = int(prom * 1.6) + seed % 25
        described = prom >= 52
        claimed = prom >= 30
    available = GBP_ATTRIBUTES[:n_attrs]
    unavailable = GBP_ATTRIBUTES[n_attrs:]
    return {
        "photos_count": photos,
        "claimed": claimed,
        "description": (f"{name} provides heating and cooling service across the "
                        f"metro area." if described else None),
        "available_attributes": available,
        "unavailable_attributes": unavailable,
    }


def _filler_field():
    """A denser background field of businesses scattered across the market.

    Real local markets have dozens of listings, not a dozen. Without that density
    the target can never actually fall out of the top results, so there are no dead
    zones to find. This lays down a deterministic ring pattern of ordinary-prominence
    businesses so the depth cutoff genuinely buries the target in contested areas,
    exactly like a real scan of a crowded category.
    """
    firsts = ["Apex", "Blue Ridge", "Cardinal", "Delta", "Evergreen", "Frontier",
              "Guardian", "Heritage", "Keystone", "Liberty", "Maple", "Oakwood",
              "Pioneer", "Redwood", "Sterling", "Union", "Valley", "Westgate",
              "Anchor", "Beacon", "Copper", "Dogwood", "Emerald", "Foxpoint",
              "Granite", "Hilltop", "Ivywood", "Juniper", "Lakeside", "Mint",
              "Northstar", "Onyx", "Parkway", "Quarry"]
    lasts = ["Heating & Cooling", "Climate Solutions", "Air Systems", "HVAC Services",
             "Comfort Experts", "Mechanical", "Air & Heat", "Thermal Services"]
    out = []
    n = len(firsts)
    for i, first in enumerate(firsts):
        # spiral the homes outward so they blanket the market at every distance band.
        # Most sit inside the typical grid so contested edges are genuinely crowded.
        ang = (i * 2.399963)  # golden-angle spread, radians
        dist = 0.6 + (i / n) * 3.9
        dn = dist * math.cos(ang)
        de = dist * math.sin(ang)
        prom = 40 + (i * 37) % 32  # ordinary prominence, 40..71, deterministic
        last = lasts[i % len(lasts)]
        out.append((f"{first} {last}", round(dn, 2), round(de, 2), prom,
                    "HVAC contractor"))
    return out


class MockProvider:
    name = "mock"

    def __init__(self, center=None, target=None, seed: int = 7):
        # center anchors the whole simulated market; target is the business the
        # operator typed, dropped in at the center so the map tells its story.
        self.center_lat, self.center_lng = center or (39.9612, -82.9988)
        self.target = target
        self.seed = seed

    def _homes(self):
        lat_per_mile = 1.0 / 69.0
        lng_per_mile = 1.0 / (69.0 * math.cos(math.radians(self.center_lat)))
        homes = []
        if self.target:
            homes.append((self.target, self.center_lat, self.center_lng,
                          TARGET_PROMINENCE, "HVAC contractor"))
        for name, dn, de, prom, cat in COMPETITORS + _filler_field():
            if self.target and name.lower() == self.target.lower():
                continue
            b_lat = self.center_lat + dn * lat_per_mile
            b_lng = self.center_lng + de * lng_per_mile
            homes.append((name, b_lat, b_lng, prom, cat))
        return homes, lat_per_mile, lng_per_mile

    def search(self, keyword: str, lat: float, lng: float, depth: int = 20):
        # deterministic per-pin noise so repeat scans are stable
        h = hashlib.md5(f"{keyword}{lat:.5f}{lng:.5f}{self.seed}".encode()).hexdigest()
        rng = random.Random(int(h[:8], 16))

        homes, lat_per_mile, lng_per_mile = self._homes()

        scored = []
        for name, b_lat, b_lng, prom, cat in homes:
            dmi = math.hypot((lat - b_lat) / lat_per_mile,
                             (lng - b_lng) / lng_per_mile)
            # proximity dominates, prominence modulates. The exponent makes the
            # penalty bite harder with distance, which is how the local pack behaves.
            # The target gets a steeper curve: it clearly wins its own home cluster
            # but falls off faster than the entrenched players, so the map shows a
            # bright core fading to invisible at the edges. That is the honest,
            # common local-pack shape, and the one worth selling against.
            is_target = self.target and name == self.target
            exp, coef = (1.7, 9.4) if is_target else (1.5, 7.0)
            score = prom - (dmi ** exp) * coef + rng.uniform(-3.5, 3.5)
            scored.append((score, name, prom, cat, dmi))

        scored.sort(reverse=True, key=lambda t: t[0])
        out = []
        for i, (score, name, prom, cat, dmi) in enumerate(scored[:depth], start=1):
            is_target = bool(self.target and name == self.target)
            item = {
                "rank": i,
                "name": name,
                "place_id": "mock_" + hashlib.md5(name.encode()).hexdigest()[:12],
                "rating": round(3.5 + prom / 100.0 * 1.4, 1),
                "reviews": int(prom * 4.2) + (int(h[8:12], 16) % 40),
                "category": cat,
                "additional_categories": (["Air conditioning contractor"]
                                          if prom >= 60 else []),
            }
            item.update(_profile(name, prom, is_target, h))
            out.append(item)
        return out
