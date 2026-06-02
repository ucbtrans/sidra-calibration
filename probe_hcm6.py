"""
probe_hcm6.py — verify template_hcm6.sipx is in HCM6 mode
Run from the sidra-calibration/ directory:
    python probe_hcm6.py
"""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

ROOT     = Path(__file__).parent.parent
TEMPLATE = ROOT / "template_hcm6.sipx"
DEBUG1   = Path(__file__).parent / "sites" / "debug_hcm6.sipx"
DEBUG2   = Path(__file__).parent / "sites" / "debug_hcm6b.sipx"

print(f"template_hcm6.sipx  exists: {TEMPLATE.exists()}, size: {TEMPLATE.stat().st_size if TEMPLATE.exists() else 'n/a'}")
print(f"debug_hcm6.sipx     exists: {DEBUG1.exists()}")
print(f"debug_hcm6b.sipx    exists: {DEBUG2.exists()}")
print()

try:
    from sidra_api import SIDRASession, _SIDRA_AVAILABLE, _SIDRA_INSTALL
    print(f"SIDRA API available: {_SIDRA_AVAILABLE}")
    print(f"SIDRA install:       {_SIDRA_INSTALL}")
except Exception as e:
    print(f"SIDRA API import error: {e}")
    sys.exit(1)

if not _SIDRA_AVAILABLE:
    print("SIDRA not available — stopping.")
    sys.exit(1)

def probe_file(path, label):
    if not path.exists():
        print(f"  {label}: NOT FOUND")
        return
    print(f"\nProbing {label}: {path}")
    try:
        with SIDRASession() as sid:
            sid.open_project(str(path))
            proj = sid._project
            print(f"  Project name: {proj.Name}")
            folders = proj.SiteFolders
            print(f"  Site folders: {folders.Count}")
            for fi in range(folders.Count):
                folder = folders[fi]
                sites = folder.Sites
                print(f"    Folder '{folder.Name}': {sites.Count} site(s)")
                for si in range(sites.Count):
                    site = sites[si]
                    hcm  = sid.is_hcm6_mode(site)
                    props = sid.introspect_roundabout_leg(site)
                    cf_props = [p for p in props if "calib" in p.lower() or "hcm" in p.lower() or "cf" in p.lower()]
                    print(f"      Site '{site.Name}': HCM6={hcm}, cf-related props={cf_props[:5]}")
    except Exception as e:
        print(f"  ERROR: {e}")

probe_file(TEMPLATE, "template_hcm6.sipx")
probe_file(DEBUG1,   "debug_hcm6.sipx")
probe_file(DEBUG2,   "debug_hcm6b.sipx")
