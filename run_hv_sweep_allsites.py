"""
run_hv_sweep_allsites.py - REAL SIDRA heavy vehicle sensitivity sweep across
all OSM-validated California SHS sites.

Sweeps the heavy vehicle share (2/6/10/15/20%) at constant total entry demand,
SIDRA Standard US, fe=1.05, Entry-Circulating Flow Adjustment = None, each site
driven to saturation. Records mean entry capacity and the change versus the 6%
baseline (to match the Task 4 analytical heavy vehicle study).

Output: output/hv_allsites/hv_allsites_summary.json
Run from sidra-calibration/:  python run_hv_sweep_allsites.py
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
OUT_DIR  = Path(__file__).parent / "output" / "hv_allsites"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_ICD    = 8.0
TOTAL_SAT  = 530         # total veh/movement (saturating); split by HV share
HV_LEVELS  = [0.02, 0.06, 0.10, 0.15, 0.20]
HV_LABELS  = ["2%", "6%", "10%", "15%", "20%"]
BASE_IDX   = 1           # 6% baseline
FE_FIXED   = 1.05
HCM6_LEGS  = [0, 2, 3, 6]
ec_setter  = PARAM_REGISTRY["ec_flow_adjustment"]["setter"]


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


def set_vols(sid, site, total, hv_pct):
    hv = max(0, round(total * hv_pct))
    lv = max(1, total - hv)
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
print("Heavy vehicle sweep (SIDRA Standard US, fe=1.05, EC=None, saturated)")
print(f"Sites: {len(usable)}   total demand={TOTAL_SAT}/movement   HV={HV_LABELS}")
print("=" * 64)

work = str(OUT_DIR / "_work_hv_all.sipx")
shutil.copy2(str(TEMPLATE), work)

records, n_ok = [], 0
try:
    with SIDRASession() as sid:
        sid.open_project(work)
        site = get_site(sid)
        site.ModelSetting.Rou_Capacity_Model = 0     # SIDRA Standard US

        for i, s in enumerate(usable):
            set_geom(sid, site, s["icd_m"], s["circ_lanes"])
            sid.set_environment_factor(site, FE_FIXED)
            ec_setter(sid, site, 0, 0)                # EC = None
            caps, vcs, ok = [], [], True
            for pct in HV_LEVELS:
                set_vols(sid, site, TOTAL_SAT, pct)
                try:
                    sid.process_site(site)
                    cap, vc = read_cap_vc(sid, site)
                except Exception as e:
                    cap, vc, ok = 0.0, 0.0, False
                    print(f"  [{i+1:02d}] {s['site_id']} HV={pct} FAIL: {e}")
                caps.append(round(cap, 1)); vcs.append(round(vc, 3))
            base = caps[BASE_IDX] if caps[BASE_IDX] else 0.0
            chg = [round((c - base) / base * 100, 2) if base else 0.0 for c in caps]
            rec = {**s, "caps": caps, "vc": vcs, "chg_pct_vs_6": chg,
                   "ok": ok and base > 0}
            records.append(rec)
            if rec["ok"]:
                n_ok += 1
            print(f"  [{i+1:02d}/{len(usable)}] {s['site_id']:16s} "
                  f"cap 2%->20% {caps[0]:.0f}->{caps[-1]:.0f}  "
                  f"chg@20%={chg[-1]:+.1f}%  v/c~{vcs[BASE_IDX]:.2f}")
finally:
    try:
        Path(work).unlink()
    except Exception:
        pass
    gc.collect()

ok_recs = [r for r in records if r["ok"]]
def col(k): return [r["chg_pct_vs_6"][k] for r in ok_recs]
summary = {
    "n_usable": len(usable), "n_ok": n_ok, "total_demand": TOTAL_SAT,
    "fe": FE_FIXED, "ec": "None", "model": "SIDRA Standard US",
    "hv_labels": HV_LABELS, "method": "REAL SIDRA v10 runs, saturated synthetic volumes",
    "mean_chg_pct_vs_6": {HV_LABELS[k]: round(float(np.mean(col(k))), 3) if ok_recs else 0.0
                          for k in range(len(HV_LEVELS))},
    "mean_cap": {HV_LABELS[k]: round(float(np.mean([r["caps"][k] for r in ok_recs])), 1)
                 if ok_recs else 0.0 for k in range(len(HV_LEVELS))},
    "sites": records,
}
out = OUT_DIR / "hv_allsites_summary.json"
out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("\n" + "=" * 64)
print(f"Done. {n_ok}/{len(usable)} sites processed.")
print(f"Mean capacity change vs 6%: {summary['mean_chg_pct_vs_6']}")
print(f"Mean capacity (veh/h):      {summary['mean_cap']}")
print(f"Saved: {out}")
