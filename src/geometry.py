"""
geometry.py
Extract roundabout geometry from OpenStreetMap using osmnx.

For each site in the site list (lat/lon), this module:
  1. Downloads the OSM road network within a small radius
  2. Identifies the roundabout junction
  3. Extracts geometric parameters needed for SIDRA:
       - inscribed_diameter_m
       - circulating_width_m  (estimated from lane count and typical widths)
       - n_entry_lanes        (per approach)
       - n_circ_lanes
       - entry_radius_m       (estimated)
       - entry_angle_deg      (estimated)

Install dependency:  pip install osmnx

Notes
-----
OSM data quality varies. When OSM is missing lane info, defaults are applied.
All values should be verified against aerial imagery before use in calibration.
"""

import math
import warnings
from dataclasses import dataclass, field
from typing import Optional

try:
    import osmnx as ox
    _OSMNX_AVAILABLE = True
except ImportError:
    _OSMNX_AVAILABLE = False

# Suppress osmnx info-level logging
if _OSMNX_AVAILABLE:
    import logging
    logging.getLogger("osmnx").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Default geometry values when OSM data is incomplete
# These are based on typical California roundabout designs (Caltrans HDM)
# ---------------------------------------------------------------------------
DEFAULTS = {
    "single_lane": {
        "inscribed_diameter_m": 40.0,
        "circulating_width_m":   7.0,
        "island_diameter_m":    20.0,
        "entry_width_m":         4.5,
        "entry_radius_m":       15.0,
        "entry_angle_deg":      25.0,
        "n_circ_lanes":          1,
        "n_entry_lanes":         1,
        "n_exit_lanes":          1,
    },
    "two_lane": {
        "inscribed_diameter_m": 60.0,
        "circulating_width_m":  10.0,
        "island_diameter_m":    30.0,
        "entry_width_m":         4.0,
        "entry_radius_m":       20.0,
        "entry_angle_deg":      30.0,
        "n_circ_lanes":          2,
        "n_entry_lanes":         2,
        "n_exit_lanes":          2,
    },
}

# Lane width assumptions (m) for estimating circulating width from lane count
LANE_WIDTH_CIRC_M = 4.5   # circulating lane width
LANE_WIDTH_ENTRY_M = 4.0  # entry lane width


# ---------------------------------------------------------------------------
# Data structure for one leg's geometry
# ---------------------------------------------------------------------------
@dataclass
class LegGeometry:
    leg_idx: int               # SIDRA orientation index (0=S, 2=E, 4=N, 6=W …)
    leg_name: str = ""
    n_entry_lanes: int = 1
    n_exit_lanes: int = 1
    n_circ_lanes: int = 1
    circulating_width_m: float = 7.0
    island_diameter_m: float = 20.0
    entry_width_m: float = 4.5
    entry_radius_m: float = 15.0
    entry_angle_deg: float = 25.0
    source: str = "default"    # "osm" or "default"


@dataclass
class RoundaboutGeometry:
    site_id: str
    lat: float
    lon: float
    n_legs: int
    legs: list[LegGeometry] = field(default_factory=list)
    inscribed_diameter_m: float = 40.0
    osm_node_id: Optional[int] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------
MIN_CACHE_ICD_M = 8.0   # smaller cached ICD values are treated as OSM misses


def get_roundabout_geometry(site_id: str, lat: float, lon: float,
                            n_legs: int, lane_config: str = "single_lane",
                            search_radius_m: float = 80.0,
                            source: str = "live",
                            cache_path: Optional[str] = None) -> RoundaboutGeometry:
    """
    Get roundabout geometry for a site.

    Parameters
    ----------
    site_id      : unique site identifier string
    lat, lon     : site coordinates (WGS84)
    n_legs       : expected number of legs
    lane_config  : 'single_lane' or 'two_lane' (used to pick defaults)
    search_radius_m : OSM search radius around the coordinates
    source       : 'cache'    - inscribed diameter from the OSM cache shipped
                                with the tool (osm/parsed.json); no network
                   'live'     - download from OSM with osmnx
                   'defaults' - design defaults only
    cache_path   : path to parsed.json (source='cache')

    OSM geometry is a screening convenience.  For calibration, geometry must
    match as-built plans or field measurements.

    Returns RoundaboutGeometry with legs populated.
    """
    geom = RoundaboutGeometry(site_id=site_id, lat=lat, lon=lon, n_legs=n_legs)

    if source == "defaults":
        geom = _apply_defaults(geom, lane_config)
        geom.notes = "Design defaults (no OSM)."
        return geom

    if source == "cache":
        return _from_cache(geom, lane_config, cache_path)

    if not _OSMNX_AVAILABLE:
        warnings.warn("osmnx not installed – using default geometry values.")
        return _apply_defaults(geom, lane_config)

    try:
        return _extract_from_osm(geom, lane_config, search_radius_m)
    except Exception as e:
        geom.notes = f"OSM extraction failed ({e}); using defaults."
        return _apply_defaults(geom, lane_config)


# ---------------------------------------------------------------------------
# OSM extraction
# ---------------------------------------------------------------------------
def _extract_from_osm(geom: RoundaboutGeometry, lane_config: str,
                      radius: float) -> RoundaboutGeometry:
    """Download local OSM graph and extract roundabout geometry."""
    G = ox.graph_from_point((geom.lat, geom.lon),
                            dist=radius, network_type="drive",
                            retain_all=True)

    # Find the nearest graph node to the coordinates
    nearest_node = ox.distance.nearest_nodes(G, geom.lon, geom.lat)
    geom.osm_node_id = int(nearest_node)

    # Get edges connected to this node
    in_edges  = list(G.in_edges(nearest_node, data=True))
    out_edges = list(G.out_edges(nearest_node, data=True))
    all_edges = in_edges + out_edges

    # Estimate inscribed diameter from OSM geometry
    geom.inscribed_diameter_m = _estimate_inscribed_diameter(G, nearest_node)

    # Determine actual leg count from connected edges (unique directions)
    unique_neighbors = set()
    for u, v, _ in all_edges:
        neighbor = v if u == nearest_node else u
        unique_neighbors.add(neighbor)
    actual_n_legs = len(unique_neighbors)
    if actual_n_legs > 0:
        geom.n_legs = actual_n_legs

    # Build leg geometries
    orientations = _assign_orientations(G, nearest_node, unique_neighbors)
    defaults = DEFAULTS.get(lane_config, DEFAULTS["single_lane"])

    for i, (neighbor, orientation) in enumerate(orientations.items()):
        edge_data = _get_edge_data(G, nearest_node, neighbor)
        # OSM lane tags reflect highway lane counts, not roundabout entry lanes.
        # Cap at the expected entry lane count from the lane_config default.
        osm_lanes = _parse_lanes(edge_data, defaults["n_entry_lanes"])
        n_lanes = min(osm_lanes, defaults["n_entry_lanes"])

        # Circulating lanes and width: use design defaults, not highway lane count.
        # OSM highway lanes overcount; California single-lane roundabouts use 7m width.
        n_circ = defaults["n_circ_lanes"]
        circ_width = defaults["circulating_width_m"]
        island_d = max(1.0, geom.inscribed_diameter_m - 2 * circ_width)

        leg = LegGeometry(
            leg_idx             = orientation,
            leg_name            = edge_data.get("name", f"Leg {i+1}"),
            n_entry_lanes       = n_lanes,
            n_exit_lanes        = n_lanes,
            n_circ_lanes        = n_circ,
            circulating_width_m = circ_width,
            island_diameter_m   = island_d,
            entry_width_m       = n_lanes * LANE_WIDTH_ENTRY_M,
            entry_radius_m      = defaults["entry_radius_m"],
            entry_angle_deg     = defaults["entry_angle_deg"],
            source              = "osm",
        )
        geom.legs.append(leg)

    if not geom.legs:
        geom.notes = "No OSM legs found; using defaults."
        return _apply_defaults(geom, lane_config)

    geom.notes = f"OSM node {geom.osm_node_id}; {len(geom.legs)} legs extracted."
    return geom


def _estimate_inscribed_diameter(G, node_id) -> float:
    """
    Estimate inscribed diameter from the roundabout node's OSM attributes,
    or fall back to a typical value based on number of circulating lanes.
    """
    node_data = G.nodes[node_id]
    # OSM sometimes stores radius on the node
    if "radius" in node_data:
        try:
            return float(node_data["radius"]) * 2.0
        except (ValueError, TypeError):
            pass
    return 40.0  # Default: 40 m inscribed diameter


def _assign_orientations(G, center_node, neighbors: set) -> dict:
    """
    Assign SIDRA leg orientation indices (0=S, 2=E, 4=N, 6=W…) to each
    neighboring node based on compass bearing from the center node.
    """
    center = G.nodes[center_node]
    cx, cy = center["x"], center["y"]

    bearings = {}
    for n in neighbors:
        nd = G.nodes[n]
        dx = nd["x"] - cx
        dy = nd["y"] - cy
        bearing_deg = math.degrees(math.atan2(dx, dy)) % 360  # 0=N, 90=E
        bearings[n] = bearing_deg

    # Give each leg the nearest free compass orientation.  SIDRA codes:
    # S=0 (leg lies south, bearing 180), SE=1, E=2, NE=3, N=4, NW=5, W=6, SW=7
    code_bearing = {4: 0.0, 3: 45.0, 2: 90.0, 1: 135.0,
                    0: 180.0, 7: 225.0, 6: 270.0, 5: 315.0}

    def gap(a, b):
        d = abs(a - b) % 360
        return min(d, 360 - d)

    pairs = sorted((gap(b, cb), n, code)
                   for n, b in bearings.items()
                   for code, cb in code_bearing.items())
    result, used = {}, set()
    for _, n, code in pairs:
        if n in result or code in used:
            continue
        result[n] = code
        used.add(code)
    return result


def _get_edge_data(G, node_a, node_b) -> dict:
    """Get attributes of the edge between two nodes."""
    try:
        data = G.get_edge_data(node_a, node_b) or G.get_edge_data(node_b, node_a)
        if isinstance(data, dict):
            # Multi-edge: take first
            if 0 in data:
                return data[0]
            return next(iter(data.values()), {})
        return data or {}
    except Exception:
        return {}


def _parse_lanes(edge_data: dict, default: int) -> int:
    """Extract lane count from OSM edge attributes."""
    for key in ("lanes", "lanes:forward", "lanes:backward"):
        val = edge_data.get(key)
        if val is not None:
            try:
                return max(1, int(str(val).split(";")[0]))
            except (ValueError, TypeError):
                pass
    return default


# ---------------------------------------------------------------------------
# Default geometry fallback
# ---------------------------------------------------------------------------
def _apply_defaults(geom: RoundaboutGeometry, lane_config: str) -> RoundaboutGeometry:
    """Populate geometry using design defaults."""
    d = DEFAULTS.get(lane_config, DEFAULTS["single_lane"])
    geom.inscribed_diameter_m = d["inscribed_diameter_m"]

    from sidra_api import LEG_ORIENTATIONS
    orientations = LEG_ORIENTATIONS.get(geom.n_legs, LEG_ORIENTATIONS[4])

    island_d = max(1.0, geom.inscribed_diameter_m - 2 * d["circulating_width_m"])
    geom.legs = [
        LegGeometry(
            leg_idx             = ori,
            leg_name            = f"Leg {i+1}",
            n_entry_lanes       = d["n_entry_lanes"],
            n_exit_lanes        = d["n_exit_lanes"],
            n_circ_lanes        = d["n_circ_lanes"],
            circulating_width_m = d["circulating_width_m"],
            island_diameter_m   = island_d,
            entry_width_m       = d["entry_width_m"],
            entry_radius_m      = d["entry_radius_m"],
            entry_angle_deg     = d["entry_angle_deg"],
            source              = "default",
        )
        for i, ori in enumerate(orientations)
    ]
    return geom


# ---------------------------------------------------------------------------
# Offline OSM cache (osm/parsed.json, shipped with the tool)
# ---------------------------------------------------------------------------
_CACHE: dict = {}


def _load_cache(cache_path: Optional[str]) -> dict:
    import json
    from pathlib import Path
    p = Path(cache_path) if cache_path else \
        Path(__file__).resolve().parents[1] / "osm" / "parsed.json"
    key = str(p)
    if key not in _CACHE:
        _CACHE[key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _CACHE[key]


def _from_cache(geom: RoundaboutGeometry, lane_config: str,
                cache_path: Optional[str]) -> RoundaboutGeometry:
    """
    Design defaults with the inscribed diameter measured from the cached
    OSM ring geometry.  Leg count and orientations come from the site list.
    """
    entry = _load_cache(cache_path).get(geom.site_id)
    geom = _apply_defaults(geom, lane_config)
    if not entry or not entry.get("found") or not entry.get("icd_m"):
        geom.notes = "Not in OSM cache; design defaults used."
        return geom
    icd = float(entry["icd_m"])
    if icd < MIN_CACHE_ICD_M:
        geom.notes = f"Cached OSM ICD {icd:.1f} m implausible; design defaults used."
        return geom
    geom.inscribed_diameter_m = icd
    geom.osm_node_id = entry.get("osm_way_id")
    for leg in geom.legs:
        leg.island_diameter_m = max(1.0, icd - 2 * leg.circulating_width_m)
        leg.source = "osm_cache"
    geom.notes = f"ICD {icd:.1f} m from OSM cache (way {entry.get('osm_way_id')}); other values are design defaults."
    return geom
