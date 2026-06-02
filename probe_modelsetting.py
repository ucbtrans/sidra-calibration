"""Probe site.ModelSetting to find the HCM 2010 vs HCM 6 vs Standard selector."""
import sys, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from sidra_api import SIDRASession

ROOT = Path(__file__).parent.parent
sipx = ROOT / "template_hcm6.sipx"
work = Path(__file__).parent / "_probe_ms.sipx"
shutil.copy2(str(sipx), str(work))

with SIDRASession() as sid:
    sid.open_project(str(work))
    proj = sid._project
    for fi in range(proj.SiteFolders.Count):
        folder = proj.SiteFolders[fi]
        for si in range(folder.Sites.Count):
            site = folder.Sites[si]
            if "Roundabout" not in site.Name:
                continue
            print(f"Site: {site.Name}")
            ms = site.ModelSetting
            print("ModelSetting properties:")
            for attr in sorted(dir(ms)):
                if attr.startswith("_"):
                    continue
                try:
                    v = getattr(ms, attr)
                    if not callable(v):
                        print(f"  {attr} = {v}")
                except Exception:
                    pass

work.unlink(missing_ok=True)
