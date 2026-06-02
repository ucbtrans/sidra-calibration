"""
run_ec_sweep_sidra.py - REAL SIDRA sweep of the Entry-Circulating Flow
Adjustment (None/Low/Medium/High) across the three US capacity models,
on one synthetic roundabout site.

Verifies the Entry_circ_adj setter and produces real data + JSON for plotting.
"""
import sys, io, json, shutil, gc
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent / "src"))
from sidra_api import SIDRASession
from param_registry import PARAM_REGISTRY
import numpy as np

ROOT     = Path(__file__).parent.parent
TEMPLATE = ROOT / "template_hcm6.sipx"
OUT      = Path(__file__).parent / "output" / "ec_sweep_sidra.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

HCM6_LEGS = [0, 2, 3, 6]
MODELS = {0: "SIDRA Standard US", 1: "HCM 2010", 2: "HCM 6"}
EC_LEVELS = [0, 1, 2, 3]
EC_LABELS = ["None", "Low", "Medium", "High"]
ICD_M, CIRC_LANES = 22.0, 1
# High synthetic volume: the Entry-Circulating Flow Adjustment only affects
# capacity when circulating flow is substantial (near/above saturation).
LV, HV = 600, 36   # per movement (synthetic, ~6% HV)

ec_setter = PARAM_REGISTRY["ec_flow_adjustment"]["setter"]


def get_site(sid):
    proj = sid._project
    for fi in range(proj.SiteFolders.Count):
        folder = proj.SiteFolders[fi]
        for si in range(folder.Sites.Count):
            s = folder.Sites[si]
            if "Roundabout" in s.Name and not s.Driveonleft:
                return s
    raise RuntimeError("US roundabout site not found.")


def set_geom(sid, site):
    for li in range(8):
        leg = sid._get_leg(site, li)
        if leg is None:
            continue
        try:
            leg.Leg_roundabout.Island_diameter = float(ICD_M)
            leg.Leg_roundabout.Num_circulating_lanes = int(CIRC_LANES)
        except Exception:
            pass


def set_vols(sid, site):
    for o in HCM6_LEGS:
        for d in HCM6_LEGS:
            if o != d:
                try:
                    sid.set_volume(site, o, d, LV, HV)
                except Exception:
                    pass


def read_caps(outputs):
    caps = [o["capacity_veh_h"] for o in outputs if o.get("capacity_veh_h", 0) > 0]
    dsat = [o["deg_satn"] for o in outputs if o.get("deg_satn", 0) > 0]
    return (float(np.mean(caps)) if caps else 0.0,
            float(np.mean(dsat)) if dsat else 0.0)


results = {"site": "synthetic", "icd_m": ICD_M, "circ_lanes": CIRC_LANES,
           "lv_per_movement": LV, "hv_per_movement": HV,
           "method": "REAL SIDRA v10 runs", "models": {}}

work = OUT.parent / "_work_ec.sipx"
shutil.copy2(str(TEMPLATE), str(work))

try:
    with SIDRASession() as sid:
        sid.open_project(str(work))
        site = get_site(sid)
        set_geom(sid, site)
        set_vols(sid, site)

        for mcode, mlabel in MODELS.items():
            site.ModelSetting.Rou_Capacity_Model = mcode
            caps, vcs = [], []
            print(f"\n=== {mlabel} ===")
            for ec in EC_LEVELS:
                ec_setter(sid, site, mcode, ec)
                sid.process_site(site)
                cap, vc = read_caps(sid.read_lane_outputs(site))
                caps.append(round(cap, 1)); vcs.append(round(vc, 3))
                print(f"  EC={EC_LABELS[ec]:7s} -> capacity {cap:7.1f} veh/h  v/c={vc:.3f}")
            base = caps[0] if caps[0] else 1.0
            gains = [round((c - base) / base * 100, 2) for c in caps]
            results["models"][mlabel] = {"caps": caps, "vc": vcs,
                                          "gain_pct_vs_None": gains,
                                          "labels": EC_LABELS}
            print(f"  gains vs None: {gains}")
finally:
    try:
        work.unlink()
    except Exception:
        pass
    gc.collect()

OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
print(f"\nSaved: {OUT}")
