"""
fetch_osm.py  —  Download and cache OSM roundabout geometry for all 58 sites.

Cache layout:
  sidra-calibration/osm/raw/{site_id}.json   raw Overpass API response
  sidra-calibration/osm/parsed.json          parsed geometry summary for all sites

Run from sidra-calibration/:
    python fetch_osm.py

Re-running is safe — cached files are never re-downloaded.
"""

import json, math, time, sys
import requests
from pathlib import Path

ROOT      = Path(__file__).parent.parent
FIG_DATA  = ROOT / "Task 4" / "figure_data.json"
OSM_DIR   = Path(__file__).parent / "osm"
RAW_DIR   = OSM_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

OVERPASS_URL  = "https://overpass-api.de/api/interpreter"
SEARCH_RADIUS = 250   # metres around each lat/lon
RETRY_DELAYS  = [5, 15, 30]   # seconds between retries
REQUEST_PAUSE = 1.5           # polite pause between requests (seconds)

# California bounding box — used to flag obviously wrong coordinates
CA_LAT = (32.0, 42.5)
CA_LON = (-124.5, -114.0)

# ── Load site list ────────────────────────────────────────────────────────────
data    = json.loads(FIG_DATA.read_text())
sites   = data["sites"]          # 58 entries with site_id, lane_config, …
latlons = data["latlons"]        # parallel list; first 58 correspond to sites

assert len(sites) <= len(latlons), "More sites than latlons — check figure_data.json"
site_latlons = latlons[:len(sites)]


# ── Overpass query builders ───────────────────────────────────────────────────
def overpass_query(lat: float, lon: float, radius: int) -> str:
    """Main query: roundabout ring + nodes + connected approach ways."""
    return f"""
[out:json][timeout:30];
way[junction=roundabout](around:{radius},{lat},{lon})->.ring;
node(w.ring)->.ring_nodes;
(
  .ring;
  .ring_nodes;
  way(bn.ring_nodes)[junction!=roundabout][highway];
);
out body;
""".strip()

def approach_query(osm_way_id: int) -> str:
    """Supplementary query: fetch approach ways for an already-known ring ID."""
    return f"""
[out:json][timeout:30];
way(id:{osm_way_id})->.ring;
node(w.ring)->.ring_nodes;
way(bn.ring_nodes)[junction!=roundabout][highway];
out body;
""".strip()


# ── Geometry helpers ──────────────────────────────────────────────────────────
def _haversine(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in metres."""
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def parse_osm_response(raw: dict, site_lat: float, site_lon: float) -> dict:
    """
    Extract geometry from a raw Overpass response.

    Returns a dict with:
      found          : bool
      osm_way_id     : int | None
      icd_m          : float | None   inscribed circle diameter (metres)
      n_ring_nodes   : int
      approach_ways  : list[dict]     each has {osm_id, name, highway, lanes}
      warning        : str | None
    """
    elements  = raw.get("elements", [])
    nodes_map = {e["id"]: e for e in elements if e["type"] == "node"}
    ways      = [e for e in elements if e["type"] == "way"]

    # Separate ring ways from approach ways
    ring_ways = [w for w in ways if w.get("tags", {}).get("junction") == "roundabout"]
    appr_ways = [w for w in ways if w.get("tags", {}).get("junction") != "roundabout"]

    if not ring_ways:
        return {"found": False, "osm_way_id": None, "icd_m": None,
                "n_ring_nodes": 0, "approach_ways": [], "warning": "no roundabout way found"}

    # Pick the ring way closest to the queried point
    def ring_centroid(w):
        lats = [nodes_map[n]["lat"] for n in w["nodes"] if n in nodes_map]
        lons = [nodes_map[n]["lon"] for n in w["nodes"] if n in nodes_map]
        return (sum(lats) / len(lats), sum(lons) / len(lons)) if lats else (0, 0)

    ring_ways.sort(key=lambda w: _haversine(site_lat, site_lon, *ring_centroid(w)))
    ring = ring_ways[0]

    # Inscribed circle diameter: average distance from centroid to ring nodes × 2
    c_lat, c_lon = ring_centroid(ring)
    radii = []
    for nid in ring["nodes"]:
        if nid in nodes_map:
            n = nodes_map[nid]
            radii.append(_haversine(c_lat, c_lon, n["lat"], n["lon"]))
    icd = round(2 * sum(radii) / len(radii), 1) if radii else None

    # Approach ways: look for ways sharing a node with the ring
    ring_node_set = set(ring["nodes"])
    connected_appr = [
        w for w in appr_ways
        if any(nid in ring_node_set for nid in w.get("nodes", []))
    ]

    approach_list = []
    for w in connected_appr:
        tags  = w.get("tags", {})
        lanes_raw = tags.get("lanes", None)
        try:
            lanes = int(lanes_raw) if lanes_raw else None
        except ValueError:
            lanes = None
        approach_list.append({
            "osm_id":  w["id"],
            "name":    tags.get("name", tags.get("ref", "")),
            "highway": tags.get("highway", ""),
            "lanes":   lanes,
        })

    return {
        "found":        True,
        "osm_way_id":   ring["id"],
        "icd_m":        icd,
        "n_ring_nodes": len(ring["nodes"]),
        "approach_ways": approach_list,
        "warning":      None,
    }


# ── Downloader with caching ───────────────────────────────────────────────────
def _overpass_post(query: str, cache_file: Path) -> dict:
    """POST query to Overpass, write to cache_file, return parsed JSON."""
    last_exc = None
    for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
        if delay:
            print(f"      retry {attempt} in {delay}s …")
            time.sleep(delay)
        try:
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
                timeout=40,
                headers={"User-Agent": "sidra-calibration/1.0 (research; akurzhan@gmail.com)"},
            )
            resp.raise_for_status()
            raw = resp.json()
            cache_file.write_text(json.dumps(raw, indent=2))
            return raw
        except Exception as exc:
            last_exc = exc
            print(f"      ERROR: {exc}")
    raise RuntimeError(f"All retries failed: {last_exc}")


def fetch_site(site_id: str, lat: float, lon: float) -> dict:
    """
    Return raw Overpass JSON for site_id ring + approaches.
    Reads from cache if available; downloads and caches otherwise.
    """
    cache_file = RAW_DIR / f"{site_id}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    query = overpass_query(lat, lon, SEARCH_RADIUS)
    return _overpass_post(query, cache_file)


def fetch_approaches(site_id: str, osm_way_id: int) -> dict:
    """
    Fetch approach ways for an already-known ring way ID.
    Cached separately as {site_id}_approaches.json.
    """
    cache_file = RAW_DIR / f"{site_id}_approaches.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    query = approach_query(osm_way_id)
    return _overpass_post(query, cache_file)


# ── Main loop ─────────────────────────────────────────────────────────────────
print("=" * 60)
print("fetch_osm.py  —  OSM roundabout geometry download")
print(f"Sites: {len(sites)}   Cache: {RAW_DIR}")
print("=" * 60)

parsed_all = {}
skipped    = []

for i, (site, ll) in enumerate(zip(sites, site_latlons)):
    site_id = site["site_id"]
    lat, lon = ll[0], ll[1]

    # Validate coordinates are inside California
    if not (CA_LAT[0] <= lat <= CA_LAT[1] and CA_LON[0] <= lon <= CA_LON[1]):
        msg = f"coordinates outside California bbox (lat={lat}, lon={lon}) — SKIPPED"
        print(f"[{i+1:02d}/{len(sites)}] {site_id:22s}  WARNING: {msg}")
        parsed_all[site_id] = {"found": False, "warning": msg,
                               "lat": lat, "lon": lon}
        skipped.append(site_id)
        continue

    cache_file = RAW_DIR / f"{site_id}.json"
    cached     = cache_file.exists()
    status     = "cached" if cached else "downloading"
    print(f"[{i+1:02d}/{len(sites)}] {site_id:22s}  {status} …", end="", flush=True)

    try:
        raw    = fetch_site(site_id, lat, lon)
        parsed = parse_osm_response(raw, lat, lon)
        parsed["lat"] = lat
        parsed["lon"] = lon

        icd_str  = f"ICD={parsed['icd_m']}m" if parsed["icd_m"] else "ICD=?"
        appr_str = f"{len(parsed['approach_ways'])} approaches"
        warn_str = f"  !! {parsed['warning']}" if parsed["warning"] else ""
        print(f"  {icd_str}  {appr_str}{warn_str}")
    except Exception as exc:
        parsed = {"found": False, "warning": str(exc), "lat": lat, "lon": lon}
        print(f"  FAILED: {exc}")

    parsed_all[site_id] = parsed

    if not cached:
        time.sleep(REQUEST_PAUSE)   # only pause after actual downloads

# ── Supplementary pass: fetch approach ways for sites missing them ────────────
print()
print("--- Supplementary approach-way fetch ---")
for site_id, parsed in parsed_all.items():
    if not parsed.get("found"):
        continue
    if parsed.get("approach_ways"):
        continue   # already have them
    way_id = parsed.get("osm_way_id")
    if not way_id:
        continue

    appr_cache = RAW_DIR / f"{site_id}_approaches.json"
    cached_a   = appr_cache.exists()
    status     = "cached" if cached_a else "downloading"
    print(f"  {site_id:22s}  approaches {status} …", end="", flush=True)
    try:
        raw_a   = fetch_approaches(site_id, way_id)
        # parse approach ways from the supplementary response
        elements  = raw_a.get("elements", [])
        nodes_map = {e["id"]: e for e in elements if e["type"] == "node"}
        ways      = [e for e in elements if e["type"] == "way"
                     and e.get("tags", {}).get("junction") != "roundabout"]
        appr_list = []
        for w in ways:
            tags = w.get("tags", {})
            lanes_raw = tags.get("lanes")
            try:
                lanes = int(lanes_raw) if lanes_raw else None
            except ValueError:
                lanes = None
            appr_list.append({
                "osm_id":  w["id"],
                "name":    tags.get("name", tags.get("ref", "")),
                "highway": tags.get("highway", ""),
                "lanes":   lanes,
            })
        parsed["approach_ways"] = appr_list
        print(f"  {len(appr_list)} approaches")
    except Exception as exc:
        print(f"  FAILED: {exc}")

    if not cached_a:
        time.sleep(REQUEST_PAUSE)

# ── Save parsed summary ───────────────────────────────────────────────────────
summary_path = OSM_DIR / "parsed.json"
summary_path.write_text(json.dumps(parsed_all, indent=2))

found   = sum(1 for v in parsed_all.values() if v.get("found"))
missing = len(parsed_all) - found
with_appr = sum(1 for v in parsed_all.values() if v.get("approach_ways"))

print()
print("=" * 60)
print(f"Done.  Found: {found}/{len(sites)}  With approaches: {with_appr}  Missing/skipped: {missing}")
if skipped:
    print(f"Skipped (bad coords): {skipped}")
print(f"Raw cache:  {RAW_DIR}  ({len(list(RAW_DIR.glob('*.json')))} files)")
print(f"Parsed summary: {summary_path}")
