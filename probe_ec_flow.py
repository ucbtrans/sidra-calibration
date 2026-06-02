"""
probe_ec_flow.py - find the Entry-Circulating Flow Adjustment API property.

Dumps ModelSetting and Leg_roundabout properties (name = value) for the US
roundabout site in the template, and flags any property whose name suggests
entry-circulating flow adjustment.
"""
import sys, shutil, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent / "src"))
from sidra_api import SIDRASession

ROOT = Path(__file__).parent.parent
sipx = ROOT / "template_hcm6.sipx"
work = Path(__file__).parent / "_probe_ec.sipx"
shutil.copy2(str(sipx), str(work))

KEYWORDS = ("circ", "entry", "ec_", "adjust", "flow", "calib", "environ", "domin")


def dump(label, obj):
    print(f"\n===== {label} =====")
    hits = []
    for attr in sorted(dir(obj)):
        if attr.startswith("_"):
            continue
        try:
            v = getattr(obj, attr)
            if callable(v):
                continue
            line = f"  {attr} = {v}"
            print(line)
            if any(k in attr.lower() for k in KEYWORDS):
                hits.append(line.strip())
        except Exception:
            pass
    if hits:
        print(f"  --- candidates in {label} ---")
        for h in hits:
            print(f"  >> {h}")


with SIDRASession() as sid:
    sid.open_project(str(work))
    proj = sid._project
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
        print("No US roundabout site found.")
    else:
        print(f"Site: {site.Name}")
        dump("site.ModelSetting", site.ModelSetting)
        # First available roundabout leg
        for leg_idx in range(8):
            leg = sid._get_leg(site, leg_idx)
            if leg is not None:
                print(f"\n(using leg orientation {leg_idx})")
                dump("leg.Leg_roundabout", leg.Leg_roundabout)
                break

work.unlink(missing_ok=True)
