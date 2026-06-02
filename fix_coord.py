"""Find correct coordinates for D04-SOL-12-44 (Route 12 at Route 113, Solano County)."""
import requests, json, math, time
from pathlib import Path

headers = {"User-Agent": "sidra-calibration/1.0 (research; akurzhan@gmail.com)"}
OSM_DIR = Path(__file__).parent / "osm"
RAW_DIR = OSM_DIR / "raw"

OVERPASS = "https://overpass-api.de/api/interpreter"

# ── Step 1: roundabouts in the Dixon/Vacaville corridor (Route 12 x Route 113)
# Route 113 runs through Dixon, CA. Route 12 crosses it there.
# Bbox: (south, west, north, east) — Dixon area
query1 = """
[out:json][timeout:30];
way[junction=roundabout](38.40,-121.90,38.60,-121.70);
(._;>;);
out body;
"""

print("Searching for roundabouts in Dixon/Vacaville corridor (Rte 12 x Rte 113)...")
resp = requests.post(OVERPASS, data={"data": query1}, headers=headers, timeout=45)
raw = resp.json()
elements = raw["elements"]
nodes = {e["id"]: e for e in elements if e["type"] == "node"}
ways  = [e for e in elements if e["type"] == "way"]

def centroid(w):
    ns = [nodes[n] for n in w["nodes"] if n in nodes]
    if not ns:
        return None, None
    return sum(n["lat"] for n in ns)/len(ns), sum(n["lon"] for n in ns)/len(ns)

print(f"Found {len(ways)} roundabouts:")
for w in ways:
    lat, lon = centroid(w)
    if lat is None: continue
    tags = w.get("tags", {})
    print(f"  way {w['id']:12d}  lat={lat:.5f}  lon={lon:.5f}  "
          f"hw={tags.get('highway','-'):12s}  name={tags.get('name', tags.get('ref','-'))}")

time.sleep(1.5)

# ── Step 2: look for a roundabout on a primary/trunk road (state highway)
primary_rabs = []
for w in ways:
    lat, lon = centroid(w)
    if lat is None: continue
    hw = w.get("tags", {}).get("highway", "")
    if hw in ("primary", "trunk", "secondary"):
        primary_rabs.append((w["id"], lat, lon, hw, w.get("tags", {})))

print(f"\nHighway-grade roundabouts: {len(primary_rabs)}")
for wid, lat, lon, hw, tags in primary_rabs:
    print(f"  way {wid}: lat={lat:.5f}  lon={lon:.5f}  hw={hw}  ref={tags.get('ref','-')}  name={tags.get('name','-')}")

# ── Step 3: for each candidate, fetch connected roads to find Route 12 / Route 113
print("\nFetching approach roads for each candidate...")
for wid, lat, lon, hw, tags in primary_rabs:
    appr_q = f"""
[out:json][timeout:20];
way(id:{wid})->.ring;
node(w.ring)->.rnodes;
way(bn.rnodes)[junction!=roundabout][highway];
out body;
"""
    r2 = requests.post(OVERPASS, data={"data": appr_q}, headers=headers, timeout=30)
    appr = r2.json()
    appr_ways = [e for e in appr["elements"] if e["type"] == "way"]
    refs = [e.get("tags", {}).get("ref", "") for e in appr_ways]
    names = [e.get("tags", {}).get("name", "") for e in appr_ways]
    print(f"  way {wid} (lat={lat:.5f}, lon={lon:.5f}):  refs={refs}  names={names[:4]}")
    time.sleep(1.0)

# ── Step 4: also try Nominatim for the intersection
print("\nNominatim geocoding...")
for q in ["Route 12 Route 113 Dixon Solano California",
          "CA 12 CA 113 Solano County",
          "SR 12 SR 113 California roundabout"]:
    r3 = requests.get("https://nominatim.openstreetmap.org/search",
                      params={"q": q, "format": "json", "limit": 3, "countrycodes": "us"},
                      headers=headers, timeout=15)
    results = r3.json()
    if results:
        for res in results:
            print(f"  '{q[:40]}' -> {res['display_name'][:60]}  lat={res['lat']}  lon={res['lon']}")
    else:
        print(f"  '{q[:40]}' -> no results")
    time.sleep(1.0)
