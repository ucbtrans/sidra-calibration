"""
run_delay_sweep_allsites.py - REAL SIDRA control-delay study across all
OSM-validated California SHS sites.

Demonstrates the key methodological point: control delay is insensitive to the
calibration parameter (fe) at low degrees of saturation, but becomes sensitive
near and above saturation. Therefore delay can only serve as a calibration
target under near-saturation field conditions.

For each site (SIDRA Standard US, EC=None), sweeps fe x total-demand and
records mean control delay and degree of saturation at every point.

Output: output/delay_allsites/delay_allsites_summary.json
Run from sidra-calibration/:  python run_delay_sweep_allsites.py
"""
import sys, json, shutil, gc, io
from pathlib import Path
import numpy as np

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent / "src"))
from sidra_api import SIDRASession
from param_registry import PARAM_REGISTRY

ROOT     = Path(__file__).parent.parent
TEMPLATE = ROOT / "template_hcm6.sipx"
OSM_FILE = Path(__file__).parent / "osm" / "parsed.json"
FIG_DATA = ROOT / "Task 4" / "figure_data.json"
OUT_DIR  = Path(__file__).parent / "output" / "delay_allsites"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_ICD   = 8.0
FE_VALUES = [0.9, 1.05, 1.2]                 # sweep the calibration parameter
VOL_LEVELS = [60, 110, 170, 250, 360, 500]   # total veh/movement -> spans v/c
HCM6_LEGS = [0, 2, 3, 6]
ec_setter = PARAM_REGISTRY["ec_flow_adjustment"]["setter"]


def get_site(sid):
    proj = sid._project
    for fi in range(proj.SiteFolders.Count):
        for si in range(proj.SiteFolders[fi].Sites.Count):
            s = proj.SiteFolders[fi].Sites[si]
            if "Roundabout" in s.Name and not s.Driveonleft:
                return s
    raise RuntimeError("US roundabout site not found.")


def set_geom(sid, site, icd_m, circ_lanes):
    for li in range(8):
        leg = sid._get_leg(site, li)
        if leg:
            try:
                leg.Leg_roundabout.Island_diameter = float(icd_m)
                leg.Leg_roundabout.Num_circulating_lanes = int(circ_lanes)
            except Exception:
                pass


def set_vols(sid, site, total):
    hv = max(1, round(total * 0.06))
    lv = max(1, total - hv)
    for o in HCM6_LEGS:
        for d in HCM6_LEGS:
            if o != d:
                try:
                    sid.set_volume(site, o, d, lv, hv)
                except Exception:
                    pass


def read_delay_vc(sid, site):
    outs = sid.read_lane_outputs(site)
    seen, delays = set(), []
    for o in outs:
        li = o["leg_idx"]
        if li not in seen:
            seen.add(li)
            dly = o.get("avg_delay_s")
            if dly is not None:
                delays.append(float(dly))
    vcs = [o["deg_satn"] for o in outs if o.get("deg_satn", 0) > 0]
    return (float(np.mean(delays)) if delays else 0.0,
            float(np.mean(vcs)) if vcs else 0.0)


osm   = json.loads(OSM_FILE.read_text())
sites = json.loads(FIG_DATA.read_text())["sites"]
usable = []
for s in sites:
    o = osm.get(s["site_id"], {})
    if not o.get("found") or not o.get("icd_m") or o["icd_m"] < MIN_ICD:
        continue
    icd  = o["icd_m"]
    circ = 2 if (icd > 35 and len(o.get("approach_ways", [])) >= 6) else 1
    usable.append({"site_id": s["site_id"], "district": s["district"],
                   "icd_m": icd, "circ_lanes": circ})

print("=" * 64)
print("Delay study (SIDRA Standard US, EC=None): fe x volume sweep")
print(f"Sites: {len(usable)}   fe={FE_VALUES}   vols={VOL_LEVELS}")
print("=" * 64)

work = str(OUT_DIR / "_work_delay_all.sipx")
shutil.copy2(str(TEMPLATE), work)

# points: list of {fe, vc, delay} across all sites
points = []
records = []
n_ok = 0
try:
    with SIDRASession() as sid:
        sid.open_project(work)
        site = get_site(sid)
        site.ModelSetting.Rou_Capacity_Model = 0
        for i, s in enumerate(usable):
            set_geom(sid, site, s["icd_m"], s["circ_lanes"])
            ec_setter(sid, site, 0, 0)
            site_pts, ok = [], True
            for fe in FE_VALUES:
                sid.set_environment_factor(site, fe)
                for vol in VOL_LEVELS:
                    set_vols(sid, site, vol)
                    try:
                        sid.process_site(site)
                        dly, vc = read_delay_vc(sid, site)
                    except Exception:
                        dly, vc, ok = 0.0, 0.0, False
                    p = {"fe": fe, "vol": vol, "vc": round(vc, 3),
                         "delay": round(dly, 2)}
                    site_pts.append(p)
                    points.append({"site": s["site_id"], **p})
            records.append({**s, "points": site_pts, "ok": ok})
            if ok:
                n_ok += 1
            # quick per-site readout: delay at lowest vs highest vol for fe=1.2 vs 0.9
            lo = [p for p in site_pts if p["vol"] == VOL_LEVELS[0]]
            hi = [p for p in site_pts if p["vol"] == VOL_LEVELS[-1]]
            spread_lo = max(q["delay"] for q in lo) - min(q["delay"] for q in lo)
            spread_hi = max(q["delay"] for q in hi) - min(q["delay"] for q in hi)
            print(f"  [{i+1:02d}/{len(usable)}] {s['site_id']:16s} "
                  f"fe-spread @low-v/c={spread_lo:5.2f}s  @high-v/c={spread_hi:6.1f}s")
finally:
    try:
        Path(work).unlink()
    except Exception:
        pass
    gc.collect()

# Aggregate: mean delay per fe in v/c bins
BINS = [(0, 0.5), (0.5, 0.85), (0.85, 1.0), (1.0, 1.5), (1.5, 5.0)]
BIN_LABELS = ["<0.5", "0.5-0.85", "0.85-1.0", "1.0-1.5", ">1.5"]
agg = {}
for fe in FE_VALUES:
    agg[fe] = []
    for lo, hi in BINS:
        ds = [p["delay"] for p in points if p["fe"] == fe and lo <= p["vc"] < hi]
        agg[fe].append(round(float(np.mean(ds)), 2) if ds else None)

summary = {
    "n_usable": len(usable), "n_ok": n_ok,
    "model": "SIDRA Standard US", "fe_values": FE_VALUES,
    "vol_levels": VOL_LEVELS, "vc_bins": BIN_LABELS,
    "method": "REAL SIDRA v10 runs, fe x volume sweep",
    "mean_delay_by_fe_and_vcbin": {str(fe): agg[fe] for fe in FE_VALUES},
    "points": points,
    "sites": records,
}
out = OUT_DIR / "delay_allsites_summary.json"
out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("\n" + "=" * 64)
print(f"Done. {n_ok}/{len(usable)} sites processed, {len(points)} points.")
print("Mean delay (s) by fe and v/c bin:")
print(f"  v/c bins: {BIN_LABELS}")
for fe in FE_VALUES:
    print(f"  fe={fe}: {agg[fe]}")
print(f"Saved: {out}")
