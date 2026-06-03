"""
probe_pedestrian.py - find how to set pedestrian crossing volumes via the API.

Dumps pedestrian-related properties on the site, on a leg, and any pedestrian
movement/OD collections, with current values.

FINDING (2026-06-02): the pedestrian crossing volume is exposed as
leg.PedMainCrossingVolume (with PedMainCrossingVolumeOption), and
site.MovementPeds reports a Count but its items are not index-accessible.
Setting the crossing volume from 0 to 400 ped/h changes NEITHER entry
capacity NOR vehicle delay, in any of the three capacity models. This is a
property of isolated roundabout analysis: pedestrians affect capacity only
through exit blocking / spillback, which isolated analysis does not model
(see Task 3 protocol). A pedestrian capacity study requires lane-based
network modeling and is out of scope for the isolated-site calibration tool.
"""
import sys, shutil, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent / "src"))
from sidra_api import SIDRASession

ROOT = Path(__file__).parent.parent
sipx = ROOT / "template_hcm6.sipx"
work = Path(__file__).parent / "_probe_ped.sipx"
shutil.copy2(str(sipx), str(work))

KW = ("ped", "cross", "walk", "foot")


def scan(label, obj, show_all=False):
    print(f"\n===== {label} =====")
    names = [a for a in sorted(dir(obj)) if not a.startswith("_")]
    hits = [a for a in names if any(k in a.lower() for k in KW)]
    target = names if show_all else hits
    for a in target:
        try:
            v = getattr(obj, a)
            if callable(v):
                if any(k in a.lower() for k in KW):
                    print(f"  (method) {a}")
                continue
            print(f"  {a} = {v}")
        except Exception as e:
            if any(k in a.lower() for k in KW):
                print(f"  {a} = <err {e}>")
    if not show_all and not hits:
        print("  (no pedestrian-keyword properties)")
    return hits


with SIDRASession() as sid:
    sid.open_project(str(work))
    proj = sid._project
    site = None
    for fi in range(proj.SiteFolders.Count):
        for si in range(proj.SiteFolders[fi].Sites.Count):
            s = proj.SiteFolders[fi].Sites[si]
            if "Roundabout" in s.Name and not s.Driveonleft:
                site = s
                break
        if site:
            break

    print(f"Site: {site.Name}")
    scan("site (pedestrian props + methods)", site)

    # Leg
    for li in range(8):
        leg = sid._get_leg(site, li)
        if leg is not None:
            print(f"\n(leg orientation {li})")
            scan("leg (pedestrian)", leg)
            # roundabout leg
            scan("leg.Leg_roundabout (pedestrian)", leg.Leg_roundabout)
            break

    # Try common pedestrian OD collection names
    for attr in ("MovementPedestrianODs", "MovementPedestrians",
                 "PedestrianODs", "PedestrianMovements"):
        try:
            coll = getattr(site, attr)
            print(f"\n>>> site.{attr} exists: {coll}")
            try:
                print(f"    Count = {coll.Count}")
            except Exception:
                pass
        except Exception:
            pass

work.unlink(missing_ok=True)
