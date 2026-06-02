"""
run_ec_sweep_allsites.py - REAL SIDRA Entry-Circulating Flow Adjustment sweep
across all OSM-validated California SHS sites.

EC adjustment affects the SIDRA Standard US model only, and only when
circulating flow is high. Each site is therefore driven to saturation with a
high synthetic volume so the adjustment has an effect to measure.

Sweeps None/Low/Medium/High per site; records mean entry capacity and v/c,
and the capacity gain versus None.

Output: output/ec_allsites/ec_allsites_summary.json
Run from sidra-calibration/:  python run_ec_sweep_allsites.py
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
OUT_DIR  = Path(__file__).parent / "output" / "ec_allsites"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_ICD   = 8.0
LV_SAT    = 500          # high synthetic volume per movement -> saturation
EC_LEVELS = [0, 1, 2, 3]
EC_LABELS = ["None", "Low", "Medium", "High"]
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


def set_vols(sid, site, lv):
    hv = max(1, round(lv * 0.06))
    for o in HCM6_LEGS:
        for d in HCM6_LEGS:
            if o != d:
                try:
                    sid.set_volume(site, o, d, lv, hv)
                except Exception:
                    pass


def read_cap_vc(sid, site):
    outs = sid.read_lane_outputs(site)
    caps = [o["capacity_veh_h"] for o in outs if o.get("capacity_veh_h", 0) > 0]
    vcs  = [o["deg_satn"] for o in outs if o.get("deg_satn", 0) > 0]
    return (float(np.mean(caps)) if caps else 0.0,
            float(np.mean(vcs)) if vcs else 0.0)


# Build usable site list
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
                   "lane_config": s["lane_config"], "icd_m": icd, "circ_lanes": circ})

print("=" * 64)
print(f"EC Flow Adjustment sweep (SIDRA Standard US, saturated volumes)")
print(f"Sites: {len(usable)} OSM-validated   LV={LV_SAT}/movement")
print("=" * 64)

work = str(OUT_DIR / "_work_ec_all.sipx")
shutil.copy2(str(TEMPLATE), work)

records = []
n_ok = 0
try:
    with SIDRASession() as sid:
        sid.open_project(work)
        site = get_site(sid)
        site.ModelSetting.Rou_Capacity_Model = 0   # SIDRA Standard US

        for i, s in enumerate(usable):
            set_geom(sid, site, s["icd_m"], s["circ_lanes"])
            set_vols(sid, site, LV_SAT)
            caps, vcs = [], []
            ok = True
            for ec in EC_LEVELS:
                ec_setter(sid, site, 0, ec)
                try:
                    sid.process_site(site)
                    cap, vc = read_cap_vc(sid, site)
                except Exception as e:
                    cap, vc, ok = 0.0, 0.0, False
                    print(f"  [{i+1:02d}/{len(usable)}] {s['site_id']} EC={ec} FAIL: {e}")
                caps.append(round(cap, 1)); vcs.append(round(vc, 3))
            base = caps[0] if caps[0] else 0.0
            gains = [round((c - base) / base * 100, 2) if base else 0.0 for c in caps]
            rec = {**s, "caps": caps, "vc": vcs, "gain_pct": gains, "ok": ok and base > 0}
            records.append(rec)
            if rec["ok"]:
                n_ok += 1
            print(f"  [{i+1:02d}/{len(usable)}] {s['site_id']:16s} ICD={s['icd_m']:.0f} "
                  f"circ={s['circ_lanes']}  cap None->High {caps[0]:.0f}->{caps[3]:.0f}  "
                  f"gainHigh={gains[3]:+.2f}%  v/c~{vcs[0]:.2f}")
finally:
    try:
        Path(work).unlink()
    except Exception:
        pass
    gc.collect()

ok_recs = [r for r in records if r["ok"]]
def col(level): return [r["gain_pct"][level] for r in ok_recs]
summary = {
    "n_usable": len(usable), "n_ok": n_ok, "lv_per_movement": LV_SAT,
    "model": "SIDRA Standard US", "ec_labels": EC_LABELS,
    "method": "REAL SIDRA v10 runs, saturated synthetic volumes",
    "mean_gain_pct": {EC_LABELS[k]: round(float(np.mean(col(k))), 3) if ok_recs else 0.0
                      for k in range(4)},
    "median_gain_pct": {EC_LABELS[k]: round(float(np.median(col(k))), 3) if ok_recs else 0.0
                        for k in range(4)},
    "max_gain_pct": {EC_LABELS[k]: round(float(np.max(col(k))), 3) if ok_recs else 0.0
                     for k in range(4)},
    "sites": records,
}
out = OUT_DIR / "ec_allsites_summary.json"
out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("\n" + "=" * 64)
print(f"Done. {n_ok}/{len(usable)} sites processed.")
print(f"Mean capacity gain vs None: {summary['mean_gain_pct']}")
print(f"Saved: {out}")
