"""Deep probe of all three templates to find model-distinguishing properties."""
import sys, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from sidra_api import SIDRASession

ROOT = Path(__file__).parent.parent

for name in ["template_standard_us", "template_hcm2010", "template_hcm6"]:
    sipx = ROOT / f"{name}.sipx"
    work = Path(__file__).parent / f"_probe_{name}.sipx"
    shutil.copy2(str(sipx), str(work))

    print("=" * 60)
    print(f"Template: {name}")
    with SIDRASession() as sid:
        sid.open_project(str(work))
        proj = sid._project
        for fi in range(proj.SiteFolders.Count):
            folder = proj.SiteFolders[fi]
            for si in range(folder.Sites.Count):
                site = folder.Sites[si]
                if "Roundabout" not in site.Name:
                    continue
                print(f"  Site: {site.Name}  Model: {site.ModelName}  LHT: {site.Driveonleft}")

                # Site-level: all non-private non-method scalar properties
                for attr in sorted(dir(site)):
                    if attr.startswith("_") or attr.startswith("get_") or attr.startswith("set_"):
                        continue
                    try:
                        v = getattr(site, attr)
                        if callable(v):
                            continue
                        print(f"    site.{attr} = {v}")
                    except Exception:
                        pass

                # First leg — HCM2010 sub-object properties
                for leg_idx in range(8):
                    leg = sid._get_leg(site, leg_idx)
                    if leg is None:
                        continue
                    rleg = leg.Leg_roundabout
                    print(f"  Leg {leg_idx}:")
                    # HCM2010 sub-object
                    try:
                        h2010 = rleg.LegRouHCM2010
                        for attr in sorted(dir(h2010)):
                            if attr.startswith("_") or attr.startswith("get_") or attr.startswith("set_"):
                                continue
                            try:
                                v = getattr(h2010, attr)
                                if not callable(v):
                                    print(f"    HCM2010.{attr} = {v}")
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"    HCM2010: {e}")
                    # HCM6 sub-object
                    try:
                        h6 = rleg.LegRouHCM6
                        for attr in sorted(dir(h6)):
                            if attr.startswith("_") or attr.startswith("get_") or attr.startswith("set_"):
                                continue
                            try:
                                v = getattr(h6, attr)
                                if not callable(v):
                                    print(f"    HCM6.{attr} = {v}")
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"    HCM6: {e}")
                    break   # first leg only

    work.unlink(missing_ok=True)
    print()
