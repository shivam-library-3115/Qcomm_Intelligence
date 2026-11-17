"""
Pincode -> (city, latitude, longitude) resolution, using India Post data via
the `indiapins` package (no external network calls).

Adapted from the batch scraper's coordinate logic. Caches are in-memory only
(per process) since the server's disk is ephemeral — the first lookup for a new
area takes a couple of seconds, later lookups in that area are instant.
"""

import math
import statistics

import indiapins

# Pincodes India Post has no (or wrong) coordinates for: (lat, lon) area centres.
MANUAL_COORDS = {
    "700014": (22.5567, 88.3647),
    "700098": (22.5700, 88.4120),   # Salt Lake, Kolkata
    "560039": (12.9431, 77.5226),   # Nayandahalli, Bengaluru
    "600080": (13.1100, 80.1830),   # Korattur, Chennai
    "600114": (12.9890, 80.1880),   # Pazhavanthangal, Chennai
}

_AREA_CACHE = {}   # prefix -> (lat, lon) | None
_LOC_CACHE = {}    # pincode -> (city, lat, lon) | None


def _km(a, b):
    return 111.0 * math.hypot(a[0] - b[0], (a[1] - b[1]) * math.cos(math.radians(a[0])))


def _office_points(pincode):
    try:
        offices = indiapins.matching(pincode)
    except ValueError:
        return [], []
    pts = [(float(o["Latitude"]), float(o["Longitude"])) for o in offices
           if o.get("Latitude") and o.get("Longitude")]
    return offices, [p for p in pts if 6 < p[0] < 37 and 68 < p[1] < 98]  # inside India


def _area_anchor(pincode):
    """Median point of every post office in the same area (pincodes sharing the
    first 4 digits). Used to throw out stray coordinates in India Post data."""
    prefix = pincode[:4]
    if prefix not in _AREA_CACHE:
        pts = []
        for n in range(100):
            pts += _office_points(f"{prefix}{n:02d}")[1]
        _AREA_CACHE[prefix] = ((statistics.median(p[0] for p in pts),
                                statistics.median(p[1] for p in pts)) if pts else None)
    return _AREA_CACHE[prefix]


def locate(pincode, city_label=None):
    """Return (city, lat, lon) for a pincode, or None if it can't be found."""
    pincode = str(pincode).strip()
    if pincode in _LOC_CACHE and pincode not in MANUAL_COORDS:
        city, lat, lon = _LOC_CACHE[pincode]
        return (city_label or city, lat, lon)

    if pincode in MANUAL_COORDS:
        lat, lon = MANUAL_COORDS[pincode]
        return (city_label or "N/A", lat, lon)

    offices, pts = _office_points(pincode)
    if not offices:
        return None
    city = city_label or offices[0].get("District", "N/A").title()

    anchor = _area_anchor(pincode)
    if anchor:
        pts = [p for p in pts if _km(p, anchor) <= 30]
    if not pts:
        if not anchor:
            return None
        pts = [anchor]

    lat = round(statistics.median(p[0] for p in pts), 4)
    lon = round(statistics.median(p[1] for p in pts), 4)
    result = (city, lat, lon)
    _LOC_CACHE[pincode] = result
    return (city_label or city, lat, lon)
