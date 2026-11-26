# -*- coding: utf-8 -*-
"""
make_sample_sipx.py - Generate reference .sipx files for the Caltrans reviewer
(Sofia Liang, Q3). Mirrors the automated pipeline used for the 47-site direct
SIDRA runs (report Section 4.6 / Conclusion 6.1.4): copy the US template, set
each site's inscribed diameter and circulating-lane count, apply moderate
AADT-derived synthetic volumes, run SIDRA Standard US at the US default fe=1.05,
then save the project file.

Single-lane and hybrid are real open California sites. The multilane case is
ILLUSTRATIVE: California's open inventory has no multilane-only roundabout.

Output: Task 6/Sample_SIDRA_Files/*.sipx
Run from sidra-calibration/:  python make_sample_sipx.py
"""
import sys, shutil, gc, io
from pathlib import Path
import numpy as np

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent / "src"))
from sidra_api import SIDRASession

ROOT     = Path(__file__).parent.parent
TEMPLATE = ROOT / "template_hcm6.sipx"
OUT_DIR  = ROOT / "Task 6" / "Sample_SIDRA_Files"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HCM6_LEGS = [0, 2, 3, 6]     # S, E, N, W (template's 4-leg layout)
LV         = 220             # moderate synthetic peak-hour volume per movement
HV_FRAC    = 0.06
FE         = 1.05            # US default, SIDRA Standard US

SAMPLES = [
    {"file": "SampleA_SingleLane_D04-SCL-152-43.sipx",
     "site_name": "D04-SCL-152-43 Single-Lane Roundabout (SIDRA Standard US, fe=1.05)",
     "icd": 32.2, "circ": 1,
     "note": "Real open CA site: District 4, Santa Clara, Route 152. Single-lane, 4-leg."},
    {"file": "SampleB_Hybrid_D07-LA-138-77.sipx",
     "site_name": "D07-LA-138-77 Hybrid Roundabout (SIDRA Standard US, fe=1.05)",
     "icd": 40.3, "circ": 2,
     "note": "Real open CA site: District 7, Los Angeles, Route 138. Hybrid, 4-leg."},
    {"file": "SampleC_Multilane_ILLUSTRATIVE.sipx",
     "site_name": "ILLUSTRATIVE Multilane Roundabout (not an as-built CA site)",
     "icd": 55.0, "circ": 2,
     "note": "ILLUSTRATIVE ONLY. No multilane-only roundabout is open on the CA SHS. "
             "Typical multilane geometry, 4-leg, 2 circulating lanes."},
]


def get_site(sid):
    proj = sid._project
    for fi in range(proj.SiteFolders.Count):
        for si in range(proj.SiteFolders[fi].Sites.Count):
            s = proj.SiteFolders[fi].Sites[si]
            if "Roundabout" in s.Name and not s.Driveonleft:
                return s
    raise RuntimeError("US roundabout site not found in template.")


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
    hv = max(1, round(lv * HV_FRAC))
    for o in HCM6_LEGS:
        for d in HCM6_LEGS:
            if o != d:
                try:
                    sid.set_volume(site, o, d, lv, hv)
                except Exception:
                    pass


def mean_cap_vc(sid, site):
    outs = sid.read_lane_outputs(site)
    caps = [o["capacity_veh_h"] for o in outs if o.get("capacity_veh_h", 0) > 0]
    vcs  = [o["deg_satn"] for o in outs if o.get("deg_satn", 0) > 0]
    return (float(np.mean(caps)) if caps else 0.0,
            float(np.mean(vcs)) if vcs else 0.0)


print("=" * 68)
print("Generating reference .sipx files (SIDRA Standard US, fe=1.05)")
print("=" * 68)

for s in SAMPLES:
    dest = str(OUT_DIR / s["file"])
    shutil.copy2(str(TEMPLATE), dest)
    try:
        with SIDRASession() as sid:
            sid.open_project(dest)
            site = get_site(sid)
            site.ModelSetting.Rou_Capacity_Model = 0      # SIDRA Standard US
            set_geom(sid, site, s["icd"], s["circ"])
            set_vols(sid, site, LV)
            sid.set_environment_factor(site, FE)
            site.Name = s["site_name"]
            try:
                sid.process_site(site)
                cap, vc = mean_cap_vc(sid, site)
                status = f"OK  mean cap={cap:.0f} veh/h  v/c={vc:.2f}"
            except Exception as e:
                status = f"processed-with-warning: {e}"
            sid.save_project()
        print(f"  {s['file']}")
        print(f"     ICD={s['icd']}m circ={s['circ']}  ->  {status}")
    except Exception as e:
        print(f"  {s['file']}  FAILED: {e}")
    finally:
        gc.collect()

print("\nSaved to:", OUT_DIR)
