"""
ERRATUM RE-RUN (November 2026) of the Section 4.3 single-model screening.

The original screening (April 2026, version 1.0 batch pipeline) built each
site with AddSite(), which gave the sites a generic, non-US model setup in
metric units, and it used the 1.0 volume generator, which under-assigned
demand at 4-leg at-grade sites.  This re-run uses the version 1.1 pipeline:
sites cloned from the US HCM (Customary) template, inscribed diameter from
the OSM cache, the corrected volume generator, synthetic "medium" volumes
(no census file, as in the original), SIDRA Standard US, fe swept from 0.5
to 2.0 in 16 steps.

Output: output/erratum/figure_data_corrected.json (same structure as
Task 4/figure_data.json) and per-site sweep results.
"""
import argparse, json, sys, io
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import run_calibration as rc
from sites import load_sites
from volumes import AADTLookup

OUT_DIR = REPO / "output" / "erratum" / "screening"
OUT_DIR.mkdir(parents=True, exist_ok=True)
rc.SITES_DIR = Path(__import__("tempfile").gettempdir()) / "sidra_erratum_work" / "screening"  # outside Dropbox (sync locks)

args = argparse.Namespace(geometry="cache", scenario="medium", hv_pct=0.06,
                          k_factor=0.09, d_factor=0.55, cross_ratio=0.5, steps=16)
model = rc.MODELS["sidra_standard_us"]
lookup = AADTLookup(str(OUT_DIR / "no_census_file.csv"))   # synthetic volumes

sites = load_sites(str(rc.SITES_CSV), status_filter="open")
fe_keys = [f"{0.5 + 0.1 * i:.1f}" for i in range(16)]
sweep = {k: {"caps": []} for k in fe_keys}
site_rows, failures = [], []

for i, site in enumerate(sites, 1):
    cache = OUT_DIR / f"{site.site_id}.json"
    if cache.exists():
        sd_min = json.loads(cache.read_text())
    else:
        print(f"[{i:02d}/{len(sites)}] {site.site_id}")
        sd = rc._process_site(site, lookup, args, model, None, None, True)
        pts = {}
        if sd.get("sensitivity"):
            for p in sd["sensitivity"].sweep:
                if "error" not in p and p.get("capacity_avg"):
                    pts[f"{p['value']:.1f}"] = p["capacity_avg"]
        kp = sd.get("key_points", {}).get("default", {})
        los = [o.get("level_of_service") for o in sd.get("lane_outputs", [])
               if o.get("level_of_service")]
        sd_min = {"site_id": site.site_id, "district": site.district,
                  "lane_config": site.lane_config,
                  "cap_default": round(kp["capacity"]) if kp.get("capacity") else None,
                  "los": los[0] if los else None, "sweep": pts,
                  "geometry_note": sd["geometry"].notes if sd.get("geometry") else None,
                  "error": None if pts else sd.get("notes")}
        cache.write_text(json.dumps(sd_min, indent=1))
    if not sd_min["sweep"]:
        failures.append((sd_min["site_id"], sd_min.get("error")))
        continue
    site_rows.append({k: sd_min[k] for k in
                      ("site_id", "district", "lane_config", "cap_default", "los")})
    for k in fe_keys:
        if k in sd_min["sweep"]:
            sweep[k]["caps"].append(sd_min["sweep"][k])

out = {"sweep": sweep, "sites": site_rows, "failures": failures,
       "note": "Corrected screening re-run, v1.1 pipeline, US HCM (Customary) setup"}
(REPO / "output" / "erratum" / "figure_data_corrected.json").write_text(
    json.dumps(out, indent=1))
print(f"Done: {len(site_rows)} sites processed, {len(failures)} failed")
