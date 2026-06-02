"""Probe template_standard_us.sipx and template_hcm2010.sipx to confirm model settings."""
import sys, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

ROOT = Path(__file__).parent.parent

for name in ["template_standard_us", "template_hcm2010", "template_hcm6"]:
    sipx = ROOT / f"{name}.sipx"
    work = Path(__file__).parent / f"_probe_{name}.sipx"
    shutil.copy2(str(sipx), str(work))

    from sidra_api import SIDRASession
    print("=" * 55)
    print(f"Template: {name}")
    with SIDRASession() as sid:
        sid.open_project(str(work))
        proj = sid._project
        for fi in range(proj.SiteFolders.Count):
            folder = proj.SiteFolders[fi]
            for si in range(folder.Sites.Count):
                site = folder.Sites[si]
                print(f"  Site: {site.Name}")
                print(f"  ModelName: {site.ModelName}")
                print(f"  Driveonleft: {site.Driveonleft}")
                print(f"  Hcm: {sid.is_hcm6_mode(site)}")
                # Check all legs for calibration properties
                for leg_idx in range(8):
                    leg = sid._get_leg(site, leg_idx)
                    if leg is None:
                        continue
                    rleg = leg.Leg_roundabout
                    props = [p for p in dir(rleg)
                             if not p.startswith("_")
                             and any(kw in p.lower() for kw in
                                     ["calib", "factor", "hcm", "gap", "follow", "critical", "tf", "tc", "cf"])]
                    print(f"  Leg {leg_idx} calibration props: {props[:15]}")
                    break  # just first leg

    work.unlink(missing_ok=True)
    print()
