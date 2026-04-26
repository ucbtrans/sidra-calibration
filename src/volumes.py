"""
volumes.py
Generate peak-hour turning movement counts for roundabout sites.

Strategy (Option C – hybrid):
  1. Use Caltrans AADT for the state route(s) at each site (authoritative)
  2. Apply K-factor and D-factor to convert AADT → peak-hour directional volume
  3. Distribute turning movements using pattern rules based on site type

AADT data source
----------------
Caltrans Traffic Data Branch publishes route-level AADT in the Traffic
Census Excel workbook (one per district), available at:
  https://dot.ca.gov/programs/traffic-operations/census

Since we cannot query the Caltrans API automatically, AADT values are loaded
from a local CSV (data/aadt/ca_route_aadt.csv) that the user downloads and
places in the data/aadt/ folder.  If the CSV is missing, a synthetic demand
level is used instead (low / medium / high scenario).

Turning movement patterns
-------------------------
Sites fall into two broad categories:
  - Ramp interchange: dominant through movement on one pair of legs,
    ramp legs have primarily turning movements
  - At-grade crossroad: more balanced flows across all legs

The heuristic rules below approximate typical conditions.
All volume estimates should be treated as planning-level inputs.
"""

import csv
import math
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# K-factor and D-factor defaults (rural/suburban state highway conditions)
# ---------------------------------------------------------------------------
K_FACTOR   = 0.09   # peak hour / AADT
D_FACTOR   = 0.55   # directional split of peak-hour volume
HV_PCT     = 0.06   # heavy vehicle percentage (default 6%)

# Synthetic AADT levels used when Caltrans data is unavailable
SYNTHETIC_AADT = {
    "low":    5_000,
    "medium": 12_000,
    "high":   25_000,
}

# Default scenario when no AADT source is available
DEFAULT_SCENARIO = "medium"


# ---------------------------------------------------------------------------
# Data structure for turning movement counts at one site
# ---------------------------------------------------------------------------
@dataclass
class TurningMovements:
    """
    OD matrix for one roundabout.

    volumes[origin_leg_idx][dest_leg_idx] = (lv_vol, hv_vol)  in veh/h
    """
    site_id:  str
    n_legs:   int
    leg_idxs: list[int]                        # SIDRA orientation indices
    volumes:  dict = field(default_factory=dict)  # (orig, dest) -> (lv, hv)
    aadt_source: str = "synthetic"
    scenario:    str = DEFAULT_SCENARIO
    notes:       str = ""


# ---------------------------------------------------------------------------
# AADT lookup
# ---------------------------------------------------------------------------
class AADTLookup:
    """
    Load Caltrans AADT values from a local CSV.

    Expected CSV columns (case-insensitive):
      district, route, pm_start, pm_end, aadt, year
    """

    def __init__(self, csv_path: str):
        self._records: list[dict] = []
        self._loaded = False
        p = Path(csv_path)
        if not p.exists():
            warnings.warn(
                f"AADT CSV not found at {csv_path}.\n"
                "Download from Caltrans Traffic Data Branch and place it there.\n"
                "Using synthetic volumes instead."
            )
            return

        with open(p, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = {h.lower().strip() for h in (reader.fieldnames or [])}
            required = {"route", "aadt"}
            if not required.issubset(headers):
                warnings.warn(
                    f"AADT CSV missing required columns {required}; "
                    "using synthetic volumes."
                )
                return
            for row in reader:
                self._records.append({k.lower().strip(): v for k, v in row.items()})
        self._loaded = bool(self._records)

    def lookup(self, route: str, pm: float, district: Optional[int] = None) -> Optional[int]:
        """
        Return AADT for the given route and postmile, or None if not found.
        Matches the closest record within ±2 PM.
        """
        if not self._loaded:
            return None

        route = str(route).strip().lstrip("0") or "0"
        candidates = []
        for r in self._records:
            if r.get("route", "").strip().lstrip("0") != route:
                continue
            if district and r.get("district", ""):
                try:
                    if int(r["district"]) != district:
                        continue
                except ValueError:
                    pass
            try:
                pm_start = float(r.get("pm_start", r.get("pm", pm)))
                pm_end   = float(r.get("pm_end",   pm_start))
                mid_pm   = (pm_start + pm_end) / 2
                dist     = abs(mid_pm - pm)
                if dist <= 2.0:
                    candidates.append((dist, int(float(r["aadt"]))))
            except (ValueError, TypeError):
                continue

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]


# ---------------------------------------------------------------------------
# Turning movement generator
# ---------------------------------------------------------------------------
def generate_turning_movements(
    site_id:    str,
    n_legs:     int,
    leg_idxs:   list[int],
    is_ramp:    bool,
    route1:     str,
    pm1:        float,
    route2:     Optional[str] = None,
    pm2:        Optional[float] = None,
    district:   Optional[int] = None,
    aadt_lookup: Optional[AADTLookup] = None,
    scenario:   str = DEFAULT_SCENARIO,
    hv_pct:     float = HV_PCT,
) -> TurningMovements:
    """
    Generate turning movement counts for a roundabout site.

    Parameters
    ----------
    site_id     : unique identifier
    n_legs      : number of legs
    leg_idxs    : SIDRA orientation indices for each leg (ordered)
    is_ramp     : True if site is a highway ramp interchange
    route1      : primary state route number
    pm1         : postmile of primary route
    route2      : cross-route number (if any)
    pm2         : postmile of cross-route
    district    : Caltrans district number
    aadt_lookup : AADTLookup instance (optional)
    scenario    : 'low'/'medium'/'high' for synthetic fallback
    hv_pct      : heavy vehicle percentage (0–1)
    """
    tm = TurningMovements(site_id=site_id, n_legs=n_legs, leg_idxs=leg_idxs,
                          scenario=scenario)

    # --- Determine peak-hour entry volumes per leg --------------------------
    aadt1 = _get_aadt(aadt_lookup, route1, pm1, district)
    aadt2 = _get_aadt(aadt_lookup, route2, pm2, district) if route2 else None

    if aadt1 is None and aadt2 is None:
        tm.aadt_source = "synthetic"
        aadt1 = SYNTHETIC_AADT[scenario]
        aadt2 = SYNTHETIC_AADT[scenario] // 2
        tm.notes = f"Synthetic AADT ({scenario}): route1={aadt1}, route2={aadt2}"
    else:
        tm.aadt_source = "caltrans_census"
        aadt1 = aadt1 or SYNTHETIC_AADT[scenario]
        aadt2 = aadt2 or (aadt1 // 2)

    # Peak-hour volumes (one direction per route)
    ph1 = int(aadt1 * K_FACTOR * D_FACTOR)
    ph2 = int((aadt2 or aadt1 // 2) * K_FACTOR * D_FACTOR)

    # --- Assign approach volumes to legs ------------------------------------
    leg_vols = _assign_approach_volumes(leg_idxs, ph1, ph2, is_ramp, n_legs)

    # --- Distribute into OD movements --------------------------------------
    tm.volumes = _distribute_od(leg_idxs, leg_vols, is_ramp, hv_pct)

    return tm


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _get_aadt(lookup: Optional[AADTLookup], route: Optional[str],
              pm: Optional[float], district: Optional[int]) -> Optional[int]:
    if lookup is None or route is None or pm is None:
        return None
    return lookup.lookup(route, pm, district)


def _assign_approach_volumes(leg_idxs: list[int], ph_main: int, ph_cross: int,
                              is_ramp: bool, n_legs: int) -> dict[int, int]:
    """
    Assign total approach (entry) volumes to each leg.

    For a ramp interchange:
      - Two "main line" legs carry the highway through volume
      - One or two "ramp" legs carry the ramp volume

    For an at-grade crossroad:
      - All legs share volume roughly equally
    """
    # Use actual leg count from OSM extraction — may differ from site CSV
    n = len(leg_idxs)
    vols = {}
    if n == 3:
        if is_ramp:
            # leg 0 = main1, leg 1 = main2, leg 2 = ramp
            vols[leg_idxs[0]] = ph_main
            vols[leg_idxs[1]] = ph_main
            vols[leg_idxs[2]] = ph_cross
        else:
            vols[leg_idxs[0]] = ph_main
            vols[leg_idxs[1]] = ph_cross
            vols[leg_idxs[2]] = ph_cross
    elif n == 4:
        if is_ramp:
            # two main legs + two ramp legs
            vols[leg_idxs[0]] = ph_main
            vols[leg_idxs[2]] = ph_main
            vols[leg_idxs[1]] = ph_cross
            vols[leg_idxs[3]] = ph_cross
        else:
            for idx in leg_idxs:
                vols[idx] = (ph_main + ph_cross) // n
    elif n == 5:
        vols[leg_idxs[0]] = ph_main
        vols[leg_idxs[2]] = ph_main
        for i in [1, 3, 4]:
            vols[leg_idxs[i]] = ph_cross // 2
    else:
        total = ph_main + ph_cross
        for idx in leg_idxs:
            vols[idx] = total // n if n > 0 else 0

    return vols


def _distribute_od(leg_idxs: list[int], leg_vols: dict[int, int],
                   is_ramp: bool, hv_pct: float) -> dict:
    """
    Split each leg's approach volume into OD movements.

    Turning proportions (simplified):
      - Through:  50%
      - Right:    25%
      - Left:     25%
    For 3-leg T-intersections, no U-turns.
    """
    n = len(leg_idxs)
    od = {}

    for i, orig in enumerate(leg_idxs):
        total = leg_vols.get(orig, 0)
        dests = [leg_idxs[j] for j in range(n) if j != i]

        if len(dests) == 0:
            continue
        elif len(dests) == 1:
            # Only one exit – all volume goes there
            splits = [1.0]
        elif len(dests) == 2:
            # T-intersection: 50/50 split
            splits = [0.5, 0.5]
        else:
            # Through gets largest share; turns split remainder
            through_share = 0.50
            turn_share    = (1.0 - through_share) / (len(dests) - 1)
            # Assume the leg directly across is "through"
            opposite_i = (i + n // 2) % n
            splits = []
            for j in range(n):
                if j == i:
                    continue
                if j == opposite_i:
                    splits.append(through_share)
                else:
                    splits.append(turn_share)

        for dest, split in zip(dests, splits):
            lv = max(1, int(total * split * (1 - hv_pct)))
            hv = max(0, int(total * split * hv_pct))
            od[(orig, dest)] = (lv, hv)

    return od
