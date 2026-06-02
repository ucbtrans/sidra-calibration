"""
Test programmatic model switching via Rou_Capacity_Model.
Runs the same site geometry/volumes through models 0, 1, 2 and records capacity.
"""
import sys, shutil, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from sidra_api import SIDRASession
import numpy as np

ROOT     = Path(__file__).parent.parent
TEMPLATE = ROOT / "template_hcm6.sipx"
work     = Path(__file__).parent / "_probe_switch.sipx"
shutil.copy2(str(TEMPLATE), str(work))

HCM6_LEGS = [0, 2, 3, 6]
LV = 23   # lv per movement (Qc~51, Group A)
HV = max(1, round(LV * 0.06))
ICD_M = 20.0   # typical small roundabout
CIRC  = 1

# Model codes to test
MODELS = {
    0: "SIDRA Standard US",
    1: "HCM 2010",
    2: "HCM 6",
}

with SIDRASession() as sid:
    sid.open_project(str(work))
    proj = sid._project

    # Get the US roundabout site
    site = None
    for fi in range(proj.SiteFolders.Count):
        folder = proj.SiteFolders[fi]
        for si in range(folder.Sites.Count):
            s = folder.Sites[si]
            if "Roundabout" in s.Name and not s.Driveonleft:
                site = s
                break
        if site:
            break

    if site is None:
        print("ERROR: no US roundabout site found")
        sys.exit(1)

    print(f"Site: {site.Name}  initial Rou_Capacity_Model={site.ModelSetting.Rou_Capacity_Model}")

    # Set geometry and volumes once
    for leg_idx in range(8):
        leg = sid._get_leg(site, leg_idx)
        if leg is None:
            continue
        rleg = leg.Leg_roundabout
        try:
            rleg.Island_diameter       = float(ICD_M)
            rleg.Num_circulating_lanes = int(CIRC)
        except Exception:
            pass
    for orig in HCM6_LEGS:
        for dest in HCM6_LEGS:
            if orig != dest:
                try:
                    sid.set_volume(site, orig, dest, LV, HV)
                except Exception:
                    pass

    # Sweep through model codes
    for code, label in MODELS.items():
        try:
            site.ModelSetting.Rou_Capacity_Model = code
            actual = site.ModelSetting.Rou_Capacity_Model
            print(f"\n--- {label} (code={code}, actual={actual}) ---")

            # Set calibration parameter to 1.0 (neutral)
            for leg_idx in range(8):
                leg = sid._get_leg(site, leg_idx)
                if leg is None:
                    continue
                rleg = leg.Leg_roundabout
                try:
                    rleg.LegRouHCM2010.Model_calib_factor = 1.0
                    rleg.LegRouHCM6.Model_calib_factor    = 1.0
                    rleg.Environment_factor = 1.0
                except Exception:
                    pass

            sid.process_site(site)
            outputs = sid.read_lane_outputs(site)
            caps = [o["capacity_veh_h"] for o in outputs if o.get("capacity_veh_h", 0) > 0]
            mean_cap = round(float(np.mean(caps))) if caps else 0
            print(f"  mean capacity = {mean_cap:,} veh/h  ({len(caps)} lanes)")
            print(f"  outputs: {[round(o.get('capacity_veh_h',0)) for o in outputs[:4]]}")

        except Exception as e:
            print(f"  ERROR with code {code}: {e}")

work.unlink(missing_ok=True)
print("\nDone.")
