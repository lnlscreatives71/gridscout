"""Grid geometry. Builds a square lattice of lat/lng points around a center."""
import math

EARTH_MILES = 3958.8


def build_grid(center_lat: float, center_lng: float, size: int = 7, radius_miles: float = 3.0):
    """Return list of dicts: {row, col, lat, lng, dist_miles}.

    size is points per side (7 -> 49 points). radius_miles is the distance from
    the center to the edge midpoint, so the grid spans 2*radius across.
    """
    if size < 2:
        raise ValueError("grid size must be >= 2")

    step = (2.0 * radius_miles) / (size - 1)
    half = (size - 1) / 2.0

    # miles per degree
    lat_deg_per_mile = 1.0 / 69.0
    lng_deg_per_mile = 1.0 / (69.0 * math.cos(math.radians(center_lat)))

    points = []
    for row in range(size):
        for col in range(size):
            dy = (half - row) * step   # north positive
            dx = (col - half) * step   # east positive
            lat = center_lat + dy * lat_deg_per_mile
            lng = center_lng + dx * lng_deg_per_mile
            points.append({
                "row": row,
                "col": col,
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "dist_miles": round(math.hypot(dx, dy), 2),
            })
    return points
