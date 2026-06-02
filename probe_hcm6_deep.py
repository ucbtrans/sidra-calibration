"""
probe_hcm6_deep.py
Deep introspection: find how to switch HCM6 mode and what cf property is called.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

ROOT     = Path(__file__).parent.parent
TEMPLATE = ROOT / "template_hcm6.sipx"

from sidra_api import SIDRASession, _SIDRA_AVAILABLE
if not _SIDRA_AVAILABLE:
    print("SIDRA unavailable"); sys.exit(1)

with SIDRASession() as sid:
    sid.open_project(str(TEMPLATE))
    proj = sid._project

    # ── Find the HCM6 roundabout site ──────────────────────────────────────
    hcm6_site = None
    std_site   = None
    for fi in range(proj.SiteFolders.Count):
        folder = proj.SiteFolders[fi]
        for si in range(folder.Sites.Count):
            site = folder.Sites[si]
            if sid.is_hcm6_mode(site) and "Roundabout" in site.Name:
                hcm6_site = site
            elif not sid.is_hcm6_mode(site):
                std_site = site

    print("=== HCM6 roundabout site:", getattr(hcm6_site, "Name", "not found"))
    print("=== SIDRA Standard site: ", getattr(std_site,  "Name", "not found"))

    # ── Introspect site-level properties ──────────────────────────────────
    if hcm6_site:
        site_props = [p for p in dir(hcm6_site) if not p.startswith("_")]
        model_props = [p for p in site_props
                       if any(kw in p.lower() for kw in
                              ["hcm", "model", "calib", "standard", "mode"])]
        print("\n--- HCM6 site model-related properties ---")
        for p in model_props:
            try:
                print(f"  {p} = {getattr(hcm6_site, p)}")
            except Exception as e:
                print(f"  {p} : ERROR {e}")

    # ── Introspect LegRouHCM6 on HCM6 site ────────────────────────────────
    if hcm6_site:
        print("\n--- LegRouHCM6 properties (HCM6 site) ---")
        for leg_idx in range(8):
            leg = sid._get_leg(hcm6_site, leg_idx)
            if leg is None:
                continue
            rleg = leg.Leg_roundabout
            hcm6leg = getattr(rleg, "LegRouHCM6", None)
            if hcm6leg:
                hcm6_props = [p for p in dir(hcm6leg) if not p.startswith("_")]
                cf_props   = [p for p in hcm6_props
                              if any(kw in p.lower() for kw in ["calib", "factor", "cf"])]
                print(f"  Leg {leg_idx}: LegRouHCM6 props = {hcm6_props[:10]}...")
                print(f"  Leg {leg_idx}: CF-related = {cf_props}")
                for p in cf_props:
                    try:
                        print(f"    {p} = {getattr(hcm6leg, p)}")
                    except Exception as e:
                        print(f"    {p} : ERROR {e}")
                break   # one leg is enough

    # ── Try setting Hcm on standard site ──────────────────────────────────
    if std_site:
        print("\n--- Attempting to set std_site.Hcm = True ---")
        try:
            std_site.Hcm = True
            print(f"  SET succeeded. Hcm is now: {std_site.Hcm}")
        except Exception as e:
            print(f"  SET failed: {e}")
        # Also try via type's setter if available
        for p in ["SetHcm", "set_hcm", "Hcm6", "UseHcm6", "GapModel"]:
            val = getattr(std_site, p, "MISSING")
            if val != "MISSING":
                print(f"  Found property: {p} = {val}")

    # ── Structure of HCM6 roundabout ──────────────────────────────────────
    if hcm6_site:
        print("\n--- HCM6 site leg structure ---")
        for leg_idx in range(8):
            leg = sid._get_leg(hcm6_site, leg_idx)
            if leg is None:
                continue
            rleg = leg.Leg_roundabout
            print(f"  Leg {leg_idx} ({leg.Name}): "
                  f"n_circ_lanes={rleg.Num_circulating_lanes}, "
                  f"circ_width={getattr(rleg,'Circulating_width','?')}, "
                  f"island_diam={getattr(rleg,'Island_diameter','?')}")
            # Count approach lanes
            try:
                n_appr = leg.LaneApproachs.Count
                print(f"    approach lanes: {n_appr}")
            except:
                pass
