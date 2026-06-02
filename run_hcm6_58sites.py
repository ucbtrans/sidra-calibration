"""
run_hcm6_58sites.py  —  HCM6 cf sweep for all OSM-validated California SHS sites.

For each usable site (ICD and circulating lanes from OSM):
  1. Copy HCM6 template (US HCM, right-hand drive)
  2. Set roundabout geometry from OSM (island diameter, circulating lanes)
  3. Set balanced entry volumes to reproduce each site's back-calculated Qc
  4. Sweep cf = [0.7 … 1.3] in 7 steps
  5. Save output/hcm6_sites/{site_id}.json

Sites without usable OSM geometry are skipped (not NSW/NZ .sipx files).

Outputs:
  sidra-calibration/output/hcm6_sites/   per-site JSON files
  sidra-calibration/output/hcm6_sites_summary.json

Run from sidra-calibration/:
    python run_hcm6_58sites.py
"""
import sys, json, shutil, math, gc, time, io
import numpy as np
from pathlib import Path

# Force UTF-8 on Windows console so SIDRA's Unicode output doesn't crash
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent / "src"))

ROOT       = Path(__file__).parent.parent
TEMPLATE   = ROOT / "template_hcm6.sipx"
OUT_DIR    = Path(__file__).parent / "output" / "hcm6_sites"
OSM_FILE   = Path(__file__).parent / "osm" / "parsed.json"
FIG_DATA   = ROOT / "Task 4" / "figure_data.json"

OUT_DIR.mkdir(parents=True, exist_ok=True)

CF_VALUES = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
MIN_ICD   = 8.0   # metres — below this OSM found the wrong feature

# Akcelik parameters used in the SIDRA Standard NSW runs that produced cap_default
# (same as generate_hv_sweep.py — Group A sites have high free-flow cap)
TF_A, TC_STD, QC_A = 2.05, 4.5, 51.0   # Group A: cap >= 1640 veh/h
TF_B                = 2.50               # Groups B-D

HCM6_LEGS = [0, 2, 3, 6]   # leg orientations in the template roundabout

# ── Load data ─────────────────────────────────────────────────────────────────
osm_data = json.loads(OSM_FILE.read_text())
fig_data = json.loads(FIG_DATA.read_text())
sites    = fig_data["sites"]        # list of 58 dicts

# ── Helpers ───────────────────────────────────────────────────────────────────
def back_calc_qc(cap_default: float) -> float:
    """
    Invert Akcelik formula C = (3600/TF) * exp(-Qc * TC / 3600)
    using the same SIDRA Standard parameters as generate_hv_sweep.py.
    Group A sites (cap >= 1640) have Qc ~ 51 veh/h.
    """
    if cap_default >= 1640:
        return QC_A
    cmax = 3600.0 / TF_B
    qc   = -(3600.0 / TC_STD) * math.log(cap_default / cmax)
    return max(qc, 1.0)


def lv_for_qc(qc: float) -> int:
    """
    Convert target Qc (veh/h) to LV per movement.
    For a 4-leg balanced roundabout: Qc ≈ 0.75 * total_entry_per_leg.
    total_entry_per_leg = 3 movements * lv_per_movement (3 destinations).
    So: qc = 0.75 * 3 * lv  =>  lv = qc / 2.25
    """
    return max(1, round(qc / 2.25))


def set_geometry(sid, site, icd_m: float, circ_lanes: int):
    """Set island diameter and circulating lane count on all legs."""
    for leg_idx in range(8):
        leg = sid._get_leg(site, leg_idx)
        if leg is None:
            continue
        rleg = leg.Leg_roundabout
        try:
            rleg.Island_diameter      = float(icd_m)
            rleg.Num_circulating_lanes = int(circ_lanes)
        except Exception:
            pass


def set_volumes(sid, site, lv_per_movement: int):
    """Set balanced through-movements; 6% HV."""
    hv = max(1, round(lv_per_movement * 0.06))
    for orig in HCM6_LEGS:
        for dest in HCM6_LEGS:
            if orig == dest:
                continue
            try:
                sid.set_volume(site, orig, dest, lv_per_movement, hv)
            except Exception:
                pass


def get_hcm6_site(sid):
    """Return the Roundabout Example US site from the open project."""
    proj = sid._project
    for fi in range(proj.SiteFolders.Count):
        folder = proj.SiteFolders[fi]
        for si in range(folder.Sites.Count):
            site = folder.Sites[si]
            if sid.is_hcm6_mode(site) and "Roundabout" in site.Name:
                return site
    raise RuntimeError("HCM6 roundabout site not found in template.")


def run_site(site_id: str, icd_m: float, circ_lanes: int,
             qc: float, lv: int) -> list[dict]:
    """
    Open a fresh copy of the HCM6 template, set geometry and volumes,
    sweep cf, return list of {cf, mean_cap, caps}.
    """
    from sidra_api import SIDRASession

    work = str(OUT_DIR / f"_work_{site_id}.sipx")
    shutil.copy2(str(TEMPLATE), work)

    results = []
    with SIDRASession() as sid:
        sid.open_project(work)
        site = get_hcm6_site(sid)

        set_geometry(sid, site, icd_m, circ_lanes)
        set_volumes(sid, site, lv)

        for cf in CF_VALUES:
            sid.set_hcm_calibration_factor(site, cf)
            try:
                sid.process_site(site)
                outputs = sid.read_lane_outputs(site)
                caps = [o["capacity_veh_h"] for o in outputs
                        if o.get("capacity_veh_h", 0) > 0]
                mean_cap = round(float(np.mean(caps))) if caps else 0
                delay_vals = [o.get("avg_delay_s", 0) for o in outputs
                              if o.get("avg_delay_s") is not None]
                mean_delay = round(float(np.mean(delay_vals)), 1) if delay_vals else None
            except Exception as e:
                print(f"      WARNING cf={cf}: {e}")
                caps, mean_cap, mean_delay = [], 0, None

            results.append({
                "cf":         cf,
                "mean_cap":   mean_cap,
                "mean_delay": mean_delay,
                "caps":       caps,
            })

    # Clean up work file
    try:
        Path(work).unlink()
    except Exception:
        pass

    return results


# ── Determine usable sites ────────────────────────────────────────────────────
usable = []
for s in sites:
    sid_  = s["site_id"]
    o     = osm_data.get(sid_, {})
    found = o.get("found", False)
    icd   = o.get("icd_m")
    if not found or icd is None or icd < MIN_ICD:
        continue
    # circulating lanes: use OSM approach count as a proxy
    # If 3+ unique approach ways share nodes and roundabout ICD > 30m → likely 2-lane
    # Conservative default: 1 lane (matches HCM6 template default)
    nappr = len(o.get("approach_ways", []))
    circ  = 2 if (icd > 35 and nappr >= 6) else 1
    qc    = back_calc_qc(s["cap_default"])
    lv    = lv_for_qc(qc)
    usable.append({
        "site_id":    sid_,
        "district":   s["district"],
        "lane_config": s["lane_config"],
        "cap_default": s["cap_default"],
        "icd_m":      icd,
        "circ_lanes": circ,
        "qc":         round(qc, 1),
        "lv":         lv,
    })

print("=" * 60)
print("HCM6 sweep — California SHS roundabouts (OSM geometry)")
print(f"Template:      {TEMPLATE}")
print(f"Sites usable:  {len(usable)}/58")
print(f"Output dir:    {OUT_DIR}")
print("=" * 60)

# ── Main loop ─────────────────────────────────────────────────────────────────
all_results = {}
for i, s in enumerate(usable):
    site_id = s["site_id"]
    out_file = OUT_DIR / f"{site_id}.json"

    if out_file.exists():
        print(f"[{i+1:02d}/{len(usable)}] {site_id}  (cached)")
        all_results[site_id] = json.loads(out_file.read_text())
        continue

    print(f"[{i+1:02d}/{len(usable)}] {site_id}  "
          f"ICD={s['icd_m']}m  circ={s['circ_lanes']}  Qc~{s['qc']:.0f}  lv={s['lv']}")

    try:
        sweep = run_site(site_id, s["icd_m"], s["circ_lanes"], s["qc"], s["lv"])
        record = {**s, "sweep": sweep}
        out_file.write_text(json.dumps(record, indent=2))
        all_results[site_id] = record

        caps_at_default = next(
            (r["mean_cap"] for r in sweep if r["cf"] == 1.0), 0)
        print(f"        cf=1.0 → {caps_at_default:,} veh/h")
    except Exception as exc:
        print(f"        FAILED: {exc}")

    gc.collect()
    time.sleep(3)   # let SIDRA COM server release file lock

# ── Summary JSON ──────────────────────────────────────────────────────────────
summary = {
    "n_sites":    len(all_results),
    "cf_values":  CF_VALUES,
    "sites":      all_results,
}
summary_path = Path(__file__).parent / "output" / "hcm6_sites_summary.json"
summary_path.write_text(json.dumps(summary, indent=2))

print()
print("=" * 60)
print(f"Done.  {len(all_results)} sites processed.")
print(f"Per-site files: {OUT_DIR}")
print(f"Summary:        {summary_path}")
