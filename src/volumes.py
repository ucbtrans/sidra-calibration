"""
volumes.py
Generate peak-hour turning movement counts for roundabout sites.

Strategy (Option C - hybrid, planning level):
  1. Look up Caltrans Traffic Census volumes for the state route(s) at the
     site (route + county + postmile)
  2. Two-way peak-hour volume = census peak hour when published,
     otherwise AADT x K
  3. Peak-direction volume per approach = two-way peak hour x D
  4. Distribute turning movements with pattern rules based on site type

These volumes are for screening and sensitivity analysis only.  For
calibration against field data, supply observed turning counts with
load_turning_counts(); they replace the generated volumes for that site.

AADT data source
----------------
The Caltrans Traffic Census (Traffic Volumes) file can be used as published:
  https://dot.ca.gov/programs/traffic-operations/census
Save it as data/aadt/ca_route_aadt.csv (or .xlsx).  The raw census layout is
read directly (DISTRICT, RTE, RTE_SFX, CNTY, PM_PFX, PM, PM_SFX, DESCRIPTION,
BACK_PEAK_HOUR, BACK_AADT, AHEAD_PEAK_HOUR, AHEAD_AADT ...).  The older
segment layout (district, route, pm_start, pm_end, aadt) is still accepted.
"""

import csv
import math
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Planning defaults (all user-configurable, see run_calibration.py options)
# ---------------------------------------------------------------------------
K_FACTOR    = 0.09   # peak hour / AADT (used only when census peak hour is missing)
D_FACTOR    = 0.55   # peak-direction share of two-way peak-hour volume
HV_PCT      = 0.06   # heavy vehicle share
CROSS_RATIO = 0.50   # local cross-road volume as a share of the state route
                     # when the cross road has no census data (placeholder,
                     # not validated against California counts)

# Largest gap (postmiles) between a site and the census point used for it
MAX_PM_DISTANCE = 5.0

# Synthetic AADT levels used when Caltrans data is unavailable
SYNTHETIC_AADT = {
    "low":    5_000,
    "medium": 12_000,
    "high":   25_000,
}

DEFAULT_SCENARIO = "medium"

# SIDRA leg orientation codes and compass labels
ORIENTATION_CODES = {"S": 0, "SE": 1, "E": 2, "NE": 3,
                     "N": 4, "NW": 5, "W": 6, "SW": 7}
ORIENTATION_LABELS = {v: k for k, v in ORIENTATION_CODES.items()}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class TrafficRecord:
    """Census volumes matched to one site postmile."""
    aadt:        Optional[int]
    peak_hour:   Optional[int]      # two-way peak-hour volume (veh/h)
    matched_pm:  float
    distance_pm: float
    side:        str                # 'ahead', 'back', 'average' or 'segment'
    description: str = ""


@dataclass
class TurningMovements:
    """
    OD matrix for one roundabout.

    volumes[(origin_leg_idx, dest_leg_idx)] = (lv_vol, hv_vol)  in veh/h
    """
    site_id:  str
    n_legs:   int
    leg_idxs: list[int]                        # SIDRA orientation indices
    volumes:  dict = field(default_factory=dict)
    aadt_source: str = "synthetic"             # synthetic | caltrans_census | observed_counts
    scenario:    str = DEFAULT_SCENARIO
    main_route:  Optional[str] = None          # state route whose census volume is used
    aadt1:       Optional[int] = None          # AADT used for the main approaches
    aadt2:       Optional[int] = None          # AADT used for the cross-road / ramp approaches
    aadt2_assumed: bool = False                # True when aadt2 = CROSS_RATIO x aadt1
    peak_hour1:  Optional[int] = None          # two-way peak hour, route 1 (veh/h)
    peak_hour2:  Optional[int] = None
    peak_hour_basis: str = ""                  # census_peak_hour | aadt_x_k
    approach_volumes: dict = field(default_factory=dict)  # leg -> veh/h
    notes:       str = ""

    @property
    def total_entry(self) -> int:
        return int(sum(lv + hv for lv, hv in self.volumes.values()))


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------
def _is_header(row) -> bool:
    cols = {_norm(c) for c in row}
    return ({"RTE", "PM"} <= cols and bool({"AHEAD_AADT", "BACK_AADT"} & cols)) \
        or {"ROUTE", "AADT"} <= cols


def _read_rows(path: Path) -> list[list]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        # Published census workbooks start with a "Preface" sheet; use the
        # first sheet that has a recognizable header row.
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        rows = []
        for ws in wb.worksheets:
            sheet = [["" if c is None else c for c in r]
                     for r in ws.iter_rows(values_only=True)]
            if any(_is_header(r) for r in sheet[:50]):
                rows = sheet
                break
        wb.close()
        return rows
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [row for row in csv.reader(f)]


def _norm(h) -> str:
    return str(h).strip().upper().replace(" ", "_")


def _num(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _route_key(route) -> str:
    return str(route).strip().upper().lstrip("0") or "0"


# ---------------------------------------------------------------------------
# AADT lookup
# ---------------------------------------------------------------------------
class AADTLookup:
    """
    Caltrans Traffic Census lookup.

    Census point layout (as published): one row per count location, with
    volumes BACK of (before) and AHEAD of (after) the postmile.  For a site
    at postmile p the nearest count location on the same route and county is
    used: AHEAD values when the location is at or before p, BACK values when
    it is at or after p.

    Segment layout (older tool format): district, route, pm_start, pm_end,
    aadt.  A segment containing the postmile is used first; otherwise the
    nearest segment end within max_distance_pm.

    California postmiles restart at each county line, so the county is
    always used when the file and the site both have it.  The district is
    used only when the county is not available.  Postmile prefixes (R, M, ...)
    are not compared.
    """

    def __init__(self, csv_path: str, max_distance_pm: float = MAX_PM_DISTANCE):
        self._records: list[dict] = []
        self._loaded = False
        self.layout: Optional[str] = None
        self.max_distance_pm = max_distance_pm
        p = Path(csv_path)
        if not p.exists():
            alt = p.with_suffix(".xlsx")
            if alt.exists():
                p = alt
            else:
                warnings.warn(
                    f"AADT file not found at {csv_path}.\n"
                    "Download the Caltrans Traffic Census file and save it "
                    "there (CSV or XLSX).  Using synthetic volumes instead."
                )
                return

        rows = _read_rows(p)
        header_idx = None
        for i, row in enumerate(rows[:50]):
            cols = {_norm(c) for c in row}
            if {"RTE", "PM"} <= cols and ({"AHEAD_AADT", "BACK_AADT"} & cols):
                header_idx, self.layout = i, "census"
                break
            if {"ROUTE", "AADT"} <= cols:
                header_idx, self.layout = i, "segment"
                break
        if header_idx is None:
            warnings.warn(
                f"{p.name}: could not find census columns (RTE, PM, BACK_AADT/"
                "AHEAD_AADT) or segment columns (route, pm_start, pm_end, "
                "aadt); using synthetic volumes."
            )
            return

        headers = [_norm(c) for c in rows[header_idx]]
        for row in rows[header_idx + 1:]:
            if not any(str(c).strip() for c in row):
                continue
            rec = {h: (row[j] if j < len(row) else "") for j, h in enumerate(headers)}
            self._records.append(rec)
        self._loaded = bool(self._records)

    # ------------------------------------------------------------------
    def lookup(self, route: str, pm: float, district: Optional[int] = None,
               county: Optional[str] = None) -> Optional[int]:
        """Return AADT for the route and postmile, or None if not found."""
        rec = self.lookup_record(route, pm, district, county)
        return rec.aadt if rec else None

    def lookup_record(self, route: str, pm: float,
                      district: Optional[int] = None,
                      county: Optional[str] = None) -> Optional[TrafficRecord]:
        if not self._loaded or route is None or pm is None:
            return None
        if self.layout == "census":
            return self._lookup_census(route, float(pm), district, county)
        return self._lookup_segment(route, float(pm), district, county)

    # ------------------------------------------------------------------
    def _same_place(self, r: dict, route: str, district, county,
                    route_col: str, district_col: str, county_col: str) -> bool:
        if _route_key(r.get(route_col, "")) != _route_key(route):
            return False
        # Suffixed routes (business, spur) are separate facilities
        if str(r.get("RTE_SFX", "")).strip() and not any(
                ch.isalpha() for ch in str(route)):
            return False
        rec_cnty = str(r.get(county_col, "")).strip().upper()
        if county and rec_cnty:
            return rec_cnty == str(county).strip().upper()
        if district and str(r.get(district_col, "")).strip():
            d = _num(r.get(district_col))
            return d is None or int(d) == int(district)
        return True

    def _lookup_census(self, route, pm, district, county) -> Optional[TrafficRecord]:
        before = after = None      # (distance, record) nearest on each side
        for r in self._records:
            if not self._same_place(r, route, district, county,
                                    "RTE", "DISTRICT", "CNTY"):
                continue
            rpm = _num(r.get("PM"))
            if rpm is None:
                continue
            d = abs(rpm - pm)
            if d > self.max_distance_pm:
                continue
            if rpm <= pm and _num(r.get("AHEAD_AADT")) is not None:
                if before is None or d < before[0]:
                    before = (d, r)
            if rpm >= pm and _num(r.get("BACK_AADT")) is not None:
                if after is None or d < after[0]:
                    after = (d, r)

        def rec_from(side, d, r):
            pfx = "AHEAD" if side == "ahead" else "BACK"
            aadt = _num(r.get(f"{pfx}_AADT"))
            ph = _num(r.get(f"{pfx}_PEAK_HOUR"))
            return TrafficRecord(
                aadt=int(aadt) if aadt is not None else None,
                peak_hour=int(ph) if ph else None,
                matched_pm=float(_num(r.get("PM"))), distance_pm=d, side=side,
                description=str(r.get("DESCRIPTION", "")).strip())

        if before and after:
            if abs(before[0] - after[0]) < 1e-9 and before[1] is not after[1]:
                a, b = rec_from("ahead", *before), rec_from("back", *after)
                ph = (round((a.peak_hour + b.peak_hour) / 2)
                      if a.peak_hour and b.peak_hour else a.peak_hour or b.peak_hour)
                return TrafficRecord(
                    aadt=round((a.aadt + b.aadt) / 2), peak_hour=ph,
                    matched_pm=a.matched_pm, distance_pm=before[0],
                    side="average",
                    description=f"{a.description} / {b.description}")
            return (rec_from("ahead", *before) if before[0] <= after[0]
                    else rec_from("back", *after))
        if before:
            return rec_from("ahead", *before)
        if after:
            return rec_from("back", *after)
        return None

    def _lookup_segment(self, route, pm, district, county) -> Optional[TrafficRecord]:
        best = None
        for r in self._records:
            if not self._same_place(r, route, district, county,
                                    "ROUTE", "DISTRICT", "COUNTY"):
                continue
            start = _num(r.get("PM_START", r.get("PM")))
            end = _num(r.get("PM_END")) if _num(r.get("PM_END")) is not None else start
            aadt = _num(r.get("AADT"))
            if start is None or aadt is None:
                continue
            lo, hi = min(start, end), max(start, end)
            d = 0.0 if lo <= pm <= hi else min(abs(pm - lo), abs(pm - hi))
            if d > self.max_distance_pm:
                continue
            if best is None or d < best[0]:
                best = (d, r, int(aadt))
        if best is None:
            return None
        d, r, aadt = best
        ph = _num(r.get("PEAK_HOUR"))
        return TrafficRecord(aadt=aadt, peak_hour=int(ph) if ph else None,
                             matched_pm=pm, distance_pm=d, side="segment")


# ---------------------------------------------------------------------------
# Observed turning counts
# ---------------------------------------------------------------------------
def _orientation(v) -> int:
    s = str(v).strip().upper()
    if s in ORIENTATION_CODES:
        return ORIENTATION_CODES[s]
    return int(float(s))


def load_turning_counts(csv_path: str) -> dict:
    """
    Read observed peak-hour turning counts.

    CSV columns: site_id, from_leg, to_leg, lv, hv
      from_leg / to_leg : compass approach (S, SE, E, NE, N, NW, W, SW)
                          or SIDRA orientation code 0-7
      lv, hv            : light and heavy vehicles (veh/h); hv may be blank

    Returns {site_id: {(from, to): (lv, hv)}}.
    """
    out: dict = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            if not row.get("site_id"):
                continue
            o, d = _orientation(row["from_leg"]), _orientation(row["to_leg"])
            lv = int(round(_num(row.get("lv")) or 0))
            hv = int(round(_num(row.get("hv")) or 0))
            out.setdefault(row["site_id"], {})[(o, d)] = (lv, hv)
    return out


def observed_turning_movements(site_id: str, leg_idxs: list[int],
                               counts: dict) -> TurningMovements:
    """Build TurningMovements from observed counts for one site."""
    unknown = sorted({o for od in counts for o in od} - set(leg_idxs))
    if unknown:
        labels = ", ".join(ORIENTATION_LABELS.get(u, str(u)) for u in unknown)
        raise ValueError(
            f"{site_id}: counts reference legs ({labels}) that are not in the "
            f"site geometry ({', '.join(ORIENTATION_LABELS[i] for i in leg_idxs)})")
    tm = TurningMovements(site_id=site_id, n_legs=len(leg_idxs),
                          leg_idxs=leg_idxs, aadt_source="observed_counts")
    tm.volumes = dict(counts)
    for (o, _d), (lv, hv) in counts.items():
        tm.approach_volumes[o] = tm.approach_volumes.get(o, 0) + lv + hv
    tm.notes = "Observed turning counts"
    return tm


# ---------------------------------------------------------------------------
# Turning movement generator
# ---------------------------------------------------------------------------
def generate_turning_movements(
    site_id:     str,
    n_legs:      int,
    leg_idxs:    list[int],
    is_ramp:     bool,
    route1:      str,
    pm1:         float,
    route2:      Optional[str] = None,
    pm2:         Optional[float] = None,
    district:    Optional[int] = None,
    aadt_lookup: Optional[AADTLookup] = None,
    scenario:    str = DEFAULT_SCENARIO,
    hv_pct:      float = HV_PCT,
    county:      Optional[str] = None,
    k_factor:    float = K_FACTOR,
    d_factor:    float = D_FACTOR,
    cross_ratio: float = CROSS_RATIO,
) -> TurningMovements:
    """
    Generate planning-level turning movements for a roundabout site.

    Each approach of a route carries the peak-direction volume
    (two-way peak hour x D), a conservative design-hour assumption.
    At interchange sites (is_ramp) the freeway (route 1) census volume is
    not used; see the comment in the body.
    """
    tm = TurningMovements(site_id=site_id, n_legs=n_legs, leg_idxs=leg_idxs,
                          scenario=scenario)

    rec1 = _get_record(aadt_lookup, route1, pm1, district, county)
    rec2 = _get_record(aadt_lookup, route2, pm2, district, county) if route2 else None
    tm.main_route = route1

    # At an interchange the census volume on route 1 is freeway mainline
    # traffic, which does not pass through the ramp-terminal roundabout.
    # Use the crossing state route (route 2) as the main road when it has
    # census data; ramp legs then get the cross-road share.
    if is_ramp:
        if rec1 is not None:
            tm.notes = (f"Interchange: route {route1} census volume is freeway "
                        "mainline and is not used; supply counts for this site. ")
        rec1, rec2 = rec2, None
        tm.main_route = route2 if rec1 is not None else None

    if rec1 is None and rec2 is None:
        tm.aadt_source = "synthetic"
        tm.main_route = None
        aadt1 = SYNTHETIC_AADT[scenario]
        ph1 = aadt1 * k_factor
        basis = "aadt_x_k"
    else:
        tm.aadt_source = "caltrans_census"
        if rec1 is not None:
            aadt1 = rec1.aadt
            ph1 = rec1.peak_hour if rec1.peak_hour else aadt1 * k_factor
            basis = "census_peak_hour" if rec1.peak_hour else "aadt_x_k"
        else:
            aadt1 = SYNTHETIC_AADT[scenario]
            ph1 = aadt1 * k_factor
            basis = "aadt_x_k"
            tm.notes += f"Route {route1} not in census; synthetic ({scenario}) used. "

    if rec2 is not None:
        aadt2 = rec2.aadt
        ph2 = rec2.peak_hour if rec2.peak_hour else aadt2 * k_factor
    else:
        aadt2 = int(round(aadt1 * cross_ratio))
        ph2 = ph1 * cross_ratio
        tm.aadt2_assumed = True

    tm.aadt1, tm.aadt2 = int(aadt1), int(aadt2)
    tm.peak_hour1, tm.peak_hour2 = int(round(ph1)), int(round(ph2))
    tm.peak_hour_basis = basis
    if rec1 is not None:
        tm.notes += (f"Route {tm.main_route} census PM {rec1.matched_pm:g} "
                     f"({rec1.side}, {rec1.distance_pm:.2f} mi from site). ")
    if tm.aadt2_assumed:
        what = "Ramp legs" if is_ramp else "Cross road"
        tm.notes += f"{what} assumed {cross_ratio:.0%} of the main road. "

    ph_main  = int(round(ph1 * d_factor))
    ph_cross = int(round(ph2 * d_factor))

    leg_vols = _assign_approach_volumes(leg_idxs, ph_main, ph_cross, is_ramp, n_legs)
    tm.approach_volumes = leg_vols
    tm.volumes = _distribute_od(leg_idxs, leg_vols, is_ramp, hv_pct)
    tm.notes = tm.notes.strip()
    return tm


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _get_record(lookup: Optional[AADTLookup], route: Optional[str],
                pm: Optional[float], district: Optional[int],
                county: Optional[str]) -> Optional[TrafficRecord]:
    if lookup is None or route is None or pm is None:
        return None
    return lookup.lookup_record(route, pm, district, county)


def _assign_approach_volumes(leg_idxs: list[int], ph_main: int, ph_cross: int,
                              is_ramp: bool, n_legs: int) -> dict[int, int]:
    """
    Assign approach (entry) volumes to each leg.

    ph_main / ph_cross are peak-direction volumes for one approach of the
    state route and of the cross road.  Every approach of a route gets that
    route's volume:
      3 legs : legs 0 and 1 on the main route, leg 2 on the cross road
      4 legs : legs 0 and 2 (opposite) main route, legs 1 and 3 cross road
    The same rule applies to ramp terminals and at-grade crossings.
    """
    n = len(leg_idxs)
    vols = {}
    if n == 3:
        vols[leg_idxs[0]] = ph_main
        vols[leg_idxs[1]] = ph_main
        vols[leg_idxs[2]] = ph_cross
    elif n == 4:
        vols[leg_idxs[0]] = ph_main
        vols[leg_idxs[2]] = ph_main
        vols[leg_idxs[1]] = ph_cross
        vols[leg_idxs[3]] = ph_cross
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


def _split_integer(total: int, shares: list[float]) -> list[int]:
    """
    Split an integer total by shares so the parts add up exactly
    (largest-remainder method).  Each part gets at least 1 vehicle when the
    total allows it, so every movement exists in SIDRA.
    """
    k = len(shares)
    if total <= 0 or k == 0:
        return [0] * k
    base = [1] * k if total >= k else [0] * k
    rest = total - sum(base)
    s = sum(shares)
    exact = [rest * sh / s for sh in shares]
    parts = [math.floor(x) for x in exact]
    left = rest - sum(parts)
    order = sorted(range(k), key=lambda i: exact[i] - parts[i], reverse=True)
    for i in order[:left]:
        parts[i] += 1
    return [b + p for b, p in zip(base, parts)]


def _distribute_od(leg_idxs: list[int], leg_vols: dict[int, int],
                   is_ramp: bool, hv_pct: float) -> dict:
    """
    Split each leg's approach volume into OD movements.

    Turning proportions (simplified):
      - Through:  50%
      - Right:    25%
      - Left:     25%
    For 3-leg sites: 50/50, no U-turns.
    Movement volumes add up exactly to the approach volume, and LV + HV
    add up exactly to each movement.
    """
    n = len(leg_idxs)
    od = {}

    for i, orig in enumerate(leg_idxs):
        total = int(leg_vols.get(orig, 0))
        dests = [leg_idxs[j] for j in range(n) if j != i]

        if len(dests) == 0:
            continue
        elif len(dests) == 1:
            splits = [1.0]
        elif len(dests) == 2:
            splits = [0.5, 0.5]
        else:
            through_share = 0.50
            turn_share    = (1.0 - through_share) / (len(dests) - 1)
            opposite_i = (i + n // 2) % n
            splits = [through_share if j == opposite_i else turn_share
                      for j in range(n) if j != i]

        for dest, mv in zip(dests, _split_integer(total, splits)):
            hv = int(round(mv * hv_pct))
            od[(orig, dest)] = (mv - hv, hv)

    return od
