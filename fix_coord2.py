"""
Locate the correct coordinates for D04-SOL-12-44 (Route 12 at Route 113, Solano Co.)
Strategy:
  1. Find where Route 12 and Route 113 intersect in OSM
  2. Check for a roundabout near that intersection
  3. Fall back to reading geometry from the existing .sipx file
"""
import sys, requests, json, math, time, gc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
OVERPASS = "https://overpass-api.de/api/interpreter"
HEADERS  = {"User-Agent": "sidra-calibration/1.0 (research; akurzhan@gmail.com)"}

def post(q, timeout=45):
    r = requests.post(OVERPASS, data={"data": q}, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()

def centroid(way, nodes):
    ns = [nodes[n] for n in way["nodes"] if n in nodes]
    if not ns: return None, None
    return sum(n["lat"] for n in ns)/len(ns), sum(n["lon"] for n in ns)/len(ns)

# ── 1. Find Route 12 and Route 113 ways in Solano County ─────────────────────
print("Step 1: finding Routes 12 and 113 in Solano County...")
q1 = """
[out:json][timeout:30];
area[name="Solano County"][admin_level=6]->.sol;
(
  way[ref="CA 12"](area.sol);
  way[ref="12"](area.sol);
  way[ref="CA 113"](area.sol);
  way[ref="113"](area.sol);
);
out body;
"""
raw1 = post(q1)
r12  = [e for e in raw1["elements"] if e["type"]=="way" and "12" in e.get("tags",{}).get("ref","")]
r113 = [e for e in raw1["elements"] if e["type"]=="way" and "113" in e.get("tags",{}).get("ref","")]
print(f"  Route 12 ways: {len(r12)}  Route 113 ways: {len(r113)}")

# Collect all node IDs from both routes
r12_nodes  = set(n for w in r12  for n in w["nodes"])
r113_nodes = set(n for w in r113 for n in w["nodes"])
shared     = r12_nodes & r113_nodes
print(f"  Shared nodes (intersection candidates): {len(shared)}")

time.sleep(1.5)

# ── 2. If we have shared nodes, get their coordinates ────────────────────────
if shared:
    node_ids = ",".join(str(n) for n in list(shared)[:20])
    q2 = f"[out:json][timeout:20];\nnode(id:{node_ids});\nout body;"
    raw2 = post(q2, timeout=25)
    inodes = {e["id"]: e for e in raw2["elements"] if e["type"]=="node"}
    print("\nIntersection nodes:")
    for nid, n in inodes.items():
        print(f"  node {nid}: lat={n['lat']:.5f}  lon={n['lon']:.5f}")
    # Use centroid of shared nodes as the intersection
    lats = [n["lat"] for n in inodes.values()]
    lons = [n["lon"] for n in inodes.values()]
    if lats:
        inter_lat = sum(lats)/len(lats)
        inter_lon = sum(lons)/len(lons)
        print(f"\nEstimated intersection: lat={inter_lat:.5f}  lon={inter_lon:.5f}")
        time.sleep(1.5)

        # ── 3. Look for roundabout within 500m of intersection ────────────────
        q3 = f"""
[out:json][timeout:30];
way[junction=roundabout](around:500,{inter_lat},{inter_lon});
(._;>;);
out body;
"""
        raw3 = post(q3)
        el3   = raw3["elements"]
        nodes3 = {{e["id"]: e for e in el3 if e["type"]=="node"}}
        ways3  = [e for e in el3 if e["type"]=="way"]
        print(f"\nRoundabouts within 500m of intersection: {len(ways3)}")
        for w in ways3:
            lat, lon = centroid(w, nodes3)
            tags = w.get("tags", {})
            print(f"  way {w['id']}: lat={lat:.5f}  lon={lon:.5f}  "
                  f"hw={tags.get('highway','-')}  name={tags.get('name','-')}")
else:
    print("  No shared nodes found — routes may not share nodes in OSM")
    inter_lat, inter_lon = 38.45, -121.82   # Dixon area fallback

time.sleep(1.5)

# ── 4. Read geometry from the .sipx file (always available) ──────────────────
print("\nStep 4: reading geometry from .sipx file...")
from sidra_api import SIDRASession

sipx = Path(__file__).parent / "sites" / "D04-SOL-12-44.sipx"
with SIDRASession() as sid:
    sid.open_project(str(sipx))
    proj = sid._project
    for fi in range(proj.SiteFolders.Count):
        folder = proj.SiteFolders[fi]
        if folder.Name != "Sites": continue
        site = folder.Sites[0]
        print(f"  Site: {site.Name}  Model: {site.ModelName}  LHT: {site.Driveonleft}")
        for leg_idx in range(8):
            leg = sid._get_leg(site, leg_idx)
            if leg is None: continue
            rleg = leg.Leg_roundabout
            print(f"  Leg {leg_idx} ({leg.Name}): "
                  f"circ_lanes={rleg.Num_circulating_lanes}  "
                  f"island_diam={rleg.Island_diameter}m  "
                  f"entry_r={rleg.Entry_radius}m  "
                  f"approach_lanes={leg.LaneApproachs.Count}")

print("\nConclusion:")
print("  The .sipx geometry is readable and will be used for the HCM6 sweep.")
print("  For the OSM coordinate: manually verify on https://www.openstreetmap.org")
print(f"  Estimated Rte 12 x Rte 113 intersection: lat~{inter_lat:.4f}, lon~{inter_lon:.4f}")
