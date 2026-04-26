"""
sites.py
Parse and classify the Caltrans roundabout site list.
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Site:
    site_id:     str
    status:      str
    district:    int
    county:      str
    route1:      str
    pm1:         float
    route2:      Optional[str]
    pm2:         Optional[float]
    n_legs:      int
    location:    str
    city:        str
    lat:         float
    lon:         float
    lane_config: str    # 'single_lane', 'hybrid', 'two_lane'
    is_ramp:     bool
    notes:       str = ""


def load_sites(csv_path: str, status_filter: str = "open") -> list[Site]:
    """
    Load and parse the Caltrans SHS roundabout list CSV.

    status_filter:
      'open'    – only completed (year-opened) roundabouts
      'all'     – include under construction and out to bid
    """
    sites = []
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Site list not found: {csv_path}")

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row_num, row in enumerate(reader, 1):
            if row_num <= 5:   # skip header rows
                continue
            if not any(row):
                continue

            status = _clean(row, 0)
            if not status:
                continue
            if status_filter == "open" and not _is_open(status):
                continue

            site = _parse_row(row, row_num)
            if site:
                sites.append(site)

    return sites


def _is_open(status: str) -> bool:
    s = status.strip().lower()
    # Open if status is a year (numeric) or a 4-digit string
    return s.isdigit() or (len(s) == 4 and s[:4].isdigit())


def _parse_row(row: list[str], row_num: int) -> Optional[Site]:
    try:
        status   = _clean(row, 0)
        district = _int(row, 3)
        county   = _clean(row, 4)
        route1   = _clean(row, 5)
        pm1      = _float(row, 6)
        route2   = _clean(row, 7) or None
        pm2_raw  = _clean(row, 8)
        pm2      = float(pm2_raw) if pm2_raw else None
        n_legs   = _int(row, 9) or 4
        location = _clean(row, 13)
        city     = _clean(row, 14)
        lat      = _float(row, 15)
        lon      = _float(row, 16)

        # Lane configuration from columns 19-21
        is_single = bool(_clean(row, 19))
        is_hybrid = bool(_clean(row, 20))
        is_multi  = bool(_clean(row, 21))
        if is_multi:
            lane_config = "two_lane"
        elif is_hybrid:
            lane_config = "hybrid"
        else:
            lane_config = "single_lane"

        # Notes column (27)
        notes = _clean(row, 27) if len(row) > 27 else ""

        # Ramp site heuristic: location description mentions "ramp"
        is_ramp = "ramp" in location.lower() or "ramps" in location.lower()

        if not lat or not lon or not route1:
            return None

        site_id = f"D{district:02d}-{county}-{route1}-{row_num}"
        return Site(
            site_id=site_id, status=status, district=district,
            county=county, route1=route1, pm1=pm1 or 0.0,
            route2=route2, pm2=pm2, n_legs=n_legs,
            location=location, city=city, lat=lat, lon=lon,
            lane_config=lane_config, is_ramp=is_ramp, notes=notes,
        )
    except Exception:
        return None


def _clean(row: list, idx: int) -> str:
    if idx >= len(row):
        return ""
    return str(row[idx]).strip()


def _int(row: list, idx: int) -> Optional[int]:
    val = _clean(row, idx).split("*")[0].strip()
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _float(row: list, idx: int) -> Optional[float]:
    val = _clean(row, idx).lstrip("RT").strip()
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
