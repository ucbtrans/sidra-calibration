"""
run_calibration.py
Main pipeline – Task 4/5: Apply SIDRA models and run calibration/sensitivity.

Usage:
    python run_calibration.py [--sites N] [--scenario low|medium|high]
                              [--param fe|cf] [--steps 16]

The script:
  1. Loads the site list from data/sites.csv
  2. Fetches geometry from OSM (or uses defaults)
  3. Generates synthetic peak-hour turning movements (Option C)
  4. Builds a SIDRA model for each site via the API
  5. Runs a sensitivity sweep over the calibration parameter
  6. Writes Excel reports to output/

No observed field data is required (synthetic volumes used).
When observed capacity is supplied (--observed-capacity), bisection
calibration is performed instead.
"""

import argparse
import sys
import os
from pathlib import Path

# Add src/ to path so imports work when running from project root
sys.path.insert(0, str(Path(__file__).parent / "src"))

from sites      import load_sites, Site
from geometry   import get_roundabout_geometry
from volumes    import AADTLookup, generate_turning_movements
from calibration import sensitivity_sweep, calibrate_bisection, FE_DEFAULT
from report     import write_site_report, write_summary_report

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT       = Path(__file__).parent
DATA_DIR   = ROOT / "data"
SITES_CSV  = DATA_DIR / "sites.csv"
AADT_CSV   = DATA_DIR / "aadt" / "ca_route_aadt.csv"
SITES_DIR  = ROOT / "sites"
OUTPUT_DIR = ROOT / "output"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="SIDRA Auto-Calibration Pipeline")
    parser.add_argument("--sites",    type=int,   default=None,
                        help="Limit to first N sites (default: all)")
    parser.add_argument("--scenario", default="medium",
                        choices=["low", "medium", "high"],
                        help="Synthetic volume scenario when AADT unavailable")
    parser.add_argument("--param",    default="fe", choices=["fe", "cf"],
                        help="Calibration parameter: fe=Environment Factor, "
                             "cf=HCM Calibration Factor")
    parser.add_argument("--steps",    type=int, default=16,
                        help="Number of steps in sensitivity sweep")
    parser.add_argument("--observed-capacity", type=float, default=None,
                        help="If provided, run bisection calibration to this "
                             "target capacity (veh/h) for all sites")
    args = parser.parse_args()

    # --- Load sites ----------------------------------------------------------
    print(f"Loading sites from {SITES_CSV} ...")
    try:
        sites = load_sites(str(SITES_CSV), status_filter="open")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"  Loaded {len(sites)} open roundabout sites.")

    if args.sites:
        sites = sites[:args.sites]
        print(f"  Processing first {len(sites)} sites.")

    # --- AADT lookup ---------------------------------------------------------
    aadt_lookup = AADTLookup(str(AADT_CSV))

    # --- SIDRA API -----------------------------------------------------------
    try:
        from sidra_api import SIDRASession
        sidra_available = True
    except Exception as e:
        print(f"Warning: SIDRA API not available ({e}).")
        print("  Running in geometry/volume-only mode (no SIDRA processing).")
        sidra_available = False

    # --- Process each site ---------------------------------------------------
    sites_data = []
    for site in sites:
        print(f"\nProcessing site {site.site_id}: {site.location[:60]}")
        sd = _process_site(site, aadt_lookup, args, sidra_available)
        sites_data.append(sd)

    # --- Write reports -------------------------------------------------------
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    site_report_path    = OUTPUT_DIR / "site_results.xlsx"
    summary_report_path = OUTPUT_DIR / "summary.xlsx"

    print(f"\nWriting site report to {site_report_path} ...")
    write_site_report(str(site_report_path), sites_data)

    print(f"Writing summary report to {summary_report_path} ...")
    write_summary_report(str(summary_report_path), sites_data)

    print("\nDone.")


# ---------------------------------------------------------------------------
# Per-site processing
# ---------------------------------------------------------------------------
def _process_site(site: Site, aadt_lookup: AADTLookup,
                  args: argparse.Namespace, sidra_available: bool) -> dict:
    sd = {
        "site_id":     site.site_id,
        "site_name":   site.location,
        "lat":         site.lat,
        "lon":         site.lon,
        "n_legs":      site.n_legs,
        "lane_config": site.lane_config,
        "district":    site.district,
        "county":      site.county,
        "route1":      site.route1,
        "aadt1":       None,
        "aadt_source": "synthetic",
        "geometry":    None,
        "turning_movements": None,
        "sensitivity": None,
        "calibration": None,
        "lane_outputs": [],
        "notes":       site.notes,
    }

    # 1. Geometry
    print(f"  Fetching geometry from OSM ...")
    geom = get_roundabout_geometry(
        site_id     = site.site_id,
        lat         = site.lat,
        lon         = site.lon,
        n_legs      = site.n_legs,
        lane_config = site.lane_config,
    )
    sd["geometry"] = geom
    print(f"  Geometry: {geom.notes or 'OK'}")

    # 2. Volumes
    print(f"  Generating turning movements ...")
    tm = generate_turning_movements(
        site_id     = site.site_id,
        n_legs      = site.n_legs,
        leg_idxs    = [leg.leg_idx for leg in geom.legs],
        is_ramp     = site.is_ramp,
        route1      = site.route1,
        pm1         = site.pm1,
        route2      = site.route2,
        pm2         = site.pm2,
        district    = site.district,
        aadt_lookup = aadt_lookup,
        scenario    = args.scenario,
    )
    sd["turning_movements"] = tm
    sd["aadt_source"] = tm.aadt_source
    # Store AADT for report
    total_entry = sum(lv + hv for lv, hv in tm.volumes.values())
    sd["aadt1"] = total_entry   # proxy for display

    if not sidra_available:
        print("  Skipping SIDRA processing (API unavailable).")
        return sd

    # 3. Build SIDRA model and run sensitivity sweep
    sipx_path = str(ROOT / "sites" / f"{site.site_id}.sipx")
    try:
        sd["sensitivity"], sd["lane_outputs"], sd["calibration"] = \
            _run_sidra(site, geom, tm, sipx_path, args)
    except Exception as e:
        print(f"  SIDRA error: {e}")
        sd["notes"] = str(e)

    return sd


def _run_sidra(site: Site, geom, tm, sipx_path: str,
               args: argparse.Namespace):
    from sidra_api import SIDRASession

    with SIDRASession() as sid:
        sid.create_project(sipx_path, site.location)
        s = sid.add_roundabout_site(site.location, len(geom.legs))

        # Configure geometry
        for leg in geom.legs:
            sid.configure_leg(
                site           = s,
                leg_orientation= leg.leg_idx,
                n_entry_lanes  = leg.n_entry_lanes,
                n_exit_lanes   = leg.n_exit_lanes,
                n_circ_lanes   = leg.n_circ_lanes,
                circ_width_m   = leg.circulating_width_m,
                island_diameter_m = leg.island_diameter_m,
                entry_width_m  = leg.entry_width_m,
                entry_radius_m = leg.entry_radius_m,
                entry_angle_deg= leg.entry_angle_deg,
                leg_name       = leg.leg_name,
            )

        sid.finalize_geometry(s)

        # Set volumes
        for (orig, dest), (lv, hv) in tm.volumes.items():
            sid.set_volume(s, orig, dest, lv, hv)

        # Run at default parameter → get baseline lane outputs
        sid.set_environment_factor(s, FE_DEFAULT)
        sid.process_site(s)
        lane_outputs = sid.read_lane_outputs(s)
        print(f"  Baseline processed. {len(lane_outputs)} lanes.")

        # Discover Environment Factor property name if needed
        props = sid.introspect_roundabout_leg(s)
        fe_props = [p for p in props if "env" in p.lower() or "factor" in p.lower()]
        if fe_props:
            print(f"  Roundabout leg properties (fe-related): {fe_props}")

        # Sensitivity sweep
        def model_fn_sweep(fe_val: float) -> dict:
            sid.set_environment_factor(s, fe_val)
            sid.process_site(s)
            outs = sid.read_lane_outputs(s)
            return {
                "capacities": [o["capacity_veh_h"] for o in outs],
                "deg_satns":  [o["deg_satn"] for o in outs],
                "avg_delays": [o["avg_delay_s"] for o in outs],
            }

        print(f"  Running sensitivity sweep ({args.steps} steps) ...")
        from calibration import sensitivity_sweep, SensitivityResult
        sweep = sensitivity_sweep(
            site_id  = site.site_id,
            model_fn = model_fn_sweep,
            param    = args.param,
            n_steps  = args.steps,
        )
        print(f"  Sweep complete: {len(sweep.sweep)} points.")

        # Bisection calibration (only if observed capacity provided)
        cal_result = None
        if args.observed_capacity:
            def model_fn_cal(fe_val: float) -> float:
                sid.set_environment_factor(s, fe_val)
                sid.process_site(s)
                outs = sid.read_lane_outputs(s)
                caps = [o["capacity_veh_h"] for o in outs if o["capacity_veh_h"] > 0]
                return sum(caps) / len(caps) if caps else 0.0

            cal_result = calibrate_bisection(
                site_id           = site.site_id,
                model_fn          = model_fn_cal,
                observed_capacity = args.observed_capacity,
                param             = args.param,
            )
            print(f"  Calibrated {args.param} = {cal_result.value:.3f} "
                  f"(error {cal_result.error_pct:.1f}%)")

        sid.save_project()

    return sweep, lane_outputs, cal_result


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
