"""
run_calibration.py
Batch screening pipeline: build SIDRA models for the inventory, run a
sensitivity sweep of the calibration parameter, and (optionally) calibrate
it to observed entry capacity.

Usage:
    python run_calibration.py [--sites N | --site-id ID ...]
                              [--model sidra_standard_us|hcm2010|hcm6]
                              [--steps 16] [--scenario low|medium|high]
                              [--observed FILE.csv | --observed-capacity C]
                              [--counts FILE.csv]
                              [--k-factor 0.09] [--d-factor 0.55]
                              [--hv-pct 0.06] [--cross-ratio 0.5]
                              [--geometry cache|live|defaults]

Steps:
  1. Load the site list from data/sites.csv
  2. Geometry from the OSM cache shipped with the tool (or live OSM, or defaults)
  3. Peak-hour turning movements: observed counts if supplied, otherwise
     planning-level volumes from the Caltrans Traffic Census
  4. Build each SIDRA site from the US template (US HCM Customary,
     right-hand traffic) and select the capacity model
  5. Sensitivity sweep of the model's parameter (fe or cf)
  6. Bisection calibration when observed capacity is supplied
  7. Excel reports in output/

For single-site, multi-target calibration with field data use
calibrate_site.py (Phase 1), calibrate_grid.py (Phase 2) or
calibrate_ga.py (Phase 3).
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from sites      import load_sites, Site
from geometry   import get_roundabout_geometry
from volumes    import (AADTLookup, generate_turning_movements,
                        load_turning_counts, observed_turning_movements,
                        K_FACTOR, D_FACTOR, HV_PCT, CROSS_RATIO,
                        ORIENTATION_CODES, ORIENTATION_LABELS)
from calibration import sensitivity_sweep, calibrate_bisection
from report     import write_site_report, write_summary_report

__version__ = "1.1.0"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT       = Path(__file__).parent
DATA_DIR   = ROOT / "data"
SITES_CSV  = DATA_DIR / "sites.csv"
AADT_CSV   = DATA_DIR / "aadt" / "ca_route_aadt.csv"
OSM_CACHE  = ROOT / "osm" / "parsed.json"
SITES_DIR  = ROOT / "sites"
OUTPUT_DIR = ROOT / "output"

# ---------------------------------------------------------------------------
# Capacity models (US right-hand traffic)
# ---------------------------------------------------------------------------
MODELS = {
    "sidra_standard_us": {"code": 0, "param": "fe", "label": "SIDRA Standard US",
                          "default": 1.05, "p_min": 0.5, "p_max": 2.0},
    "hcm2010":           {"code": 1, "param": "cf", "label": "HCM 2010",
                          "default": 1.00, "p_min": 0.7, "p_max": 1.3},
    "hcm6":              {"code": 2, "param": "cf", "label": "HCM 6",
                          "default": 1.00, "p_min": 0.7, "p_max": 1.3},
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description=f"SIDRA Auto-Calibration Pipeline v{__version__}")
    parser.add_argument("--sites", type=int, default=None,
                        help="Limit to the first N sites")
    parser.add_argument("--site-id", action="append", default=None,
                        help="Process only this site ID (repeatable)")
    parser.add_argument("--model", choices=list(MODELS), default=None,
                        help="Roundabout capacity model (default: "
                             "sidra_standard_us, or hcm6 with --param cf)")
    parser.add_argument("--param", choices=["fe", "cf"], default=None,
                        help="Kept for compatibility: fe selects "
                             "sidra_standard_us, cf selects hcm6")
    parser.add_argument("--steps", type=int, default=16,
                        help="Number of steps in the sensitivity sweep")
    parser.add_argument("--scenario", default="medium",
                        choices=["low", "medium", "high"],
                        help="Synthetic volume level when census data is missing")
    parser.add_argument("--observed", default=None,
                        help="CSV of observed capacity per site: "
                             "site_id, capacity_veh_h[, leg]")
    parser.add_argument("--observed-capacity", type=float, default=None,
                        help="One observed capacity (veh/h) applied to every "
                             "selected site; prefer --observed")
    parser.add_argument("--counts", default=None,
                        help="CSV of observed turning counts: "
                             "site_id, from_leg, to_leg, lv, hv")
    parser.add_argument("--aadt-file", default=str(AADT_CSV),
                        help="Caltrans Traffic Census file (CSV or XLSX)")
    parser.add_argument("--k-factor", type=float, default=K_FACTOR,
                        help="Peak hour / AADT, used when the census has no "
                             "peak-hour volume")
    parser.add_argument("--d-factor", type=float, default=D_FACTOR,
                        help="Peak-direction share of peak-hour volume")
    parser.add_argument("--hv-pct", type=float, default=HV_PCT,
                        help="Heavy vehicle share (0-1)")
    parser.add_argument("--cross-ratio", type=float, default=CROSS_RATIO,
                        help="Cross-road volume as a share of route 1 when the "
                             "cross road has no census data")
    parser.add_argument("--geometry", choices=["cache", "live", "defaults"],
                        default="cache",
                        help="cache: OSM data shipped with the tool (no network); "
                             "live: download from OSM; defaults: design values")
    args = parser.parse_args()

    # --- Model / parameter -------------------------------------------------
    if args.model is None:
        args.model = "hcm6" if args.param == "cf" else "sidra_standard_us"
    model = MODELS[args.model]
    if args.param and args.param != model["param"]:
        parser.error(f"--param {args.param} does not belong to --model "
                     f"{args.model} (its parameter is {model['param']})")
    args.param = model["param"]
    print(f"Capacity model: {model['label']}  parameter: {args.param} "
          f"[{model['p_min']}-{model['p_max']}], default {model['default']}")

    # --- Sites ---------------------------------------------------------------
    print(f"Loading sites from {SITES_CSV} ...")
    try:
        sites = load_sites(str(SITES_CSV), status_filter="open")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"  Loaded {len(sites)} open roundabout sites.")

    if args.site_id:
        wanted = set(args.site_id)
        missing = wanted - {s.site_id for s in sites}
        if missing:
            print(f"Error: unknown site ID(s): {', '.join(sorted(missing))}")
            sys.exit(1)
        sites = [s for s in sites if s.site_id in wanted]
    if args.sites:
        sites = sites[:args.sites]
    print(f"  Processing {len(sites)} site(s).")

    # --- Observed data -------------------------------------------------------
    observed = load_observed_capacity(args.observed) if args.observed else {}
    counts = load_turning_counts(args.counts) if args.counts else {}

    # --- AADT ----------------------------------------------------------------
    aadt_lookup = AADTLookup(args.aadt_file)
    if aadt_lookup.layout:
        print(f"  Traffic census file read ({aadt_lookup.layout} layout).")

    # --- SIDRA API -----------------------------------------------------------
    try:
        from sidra_api import SIDRASession  # noqa: F401
        sidra_available = True
    except Exception as e:
        print(f"Warning: SIDRA API not available ({e}).")
        print("  Running in geometry/volume-only mode (no SIDRA processing).")
        sidra_available = False

    sites_data = []
    for site in sites:
        print(f"\nProcessing site {site.site_id}: {site.location[:60]}")
        target = observed.get(site.site_id)
        if target is None and args.observed_capacity:
            target = [(None, args.observed_capacity)]
        sd = _process_site(site, aadt_lookup, args, model, target,
                           counts.get(site.site_id), sidra_available)
        sites_data.append(sd)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    site_report_path    = OUTPUT_DIR / "site_results.xlsx"
    summary_report_path = OUTPUT_DIR / "summary.xlsx"
    print(f"\nWriting site report to {site_report_path} ...")
    write_site_report(str(site_report_path), sites_data)
    print(f"Writing summary report to {summary_report_path} ...")
    write_summary_report(str(summary_report_path), sites_data)
    print("\nDone.")


# ---------------------------------------------------------------------------
# Observed capacity table
# ---------------------------------------------------------------------------
def load_observed_capacity(csv_path: str) -> dict:
    """
    CSV columns: site_id, capacity_veh_h, leg (optional)
      leg : compass approach (S, E, N, W, ...) whose entry lanes were observed.
            Blank = compare with the average of all entry lanes.
    Several rows per site (different legs) are averaged.
    Returns {site_id: [(leg_code or None, capacity), ...]}.
    """
    out: dict = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            if not row.get("site_id") or not row.get("capacity_veh_h"):
                continue
            leg = row.get("leg", "")
            leg_code = ORIENTATION_CODES[leg.upper()] if leg else None
            out.setdefault(row["site_id"], []).append(
                (leg_code, float(row["capacity_veh_h"])))
    return out


# ---------------------------------------------------------------------------
# Per-site processing
# ---------------------------------------------------------------------------
def _process_site(site: Site, aadt_lookup: AADTLookup,
                  args: argparse.Namespace, model: dict, target,
                  site_counts, sidra_available: bool) -> dict:
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
        "route2":      site.route2,
        "model":       model["label"],
        "param":       model["param"],
        "param_default": model["default"],
        "geometry":    None,
        "turning_movements": None,
        "sensitivity": None,
        "calibration": None,
        "key_points":  {},
        "lane_outputs": [],
        "notes":       site.notes,
    }

    # 1. Geometry
    geom = get_roundabout_geometry(
        site_id     = site.site_id,
        lat         = site.lat,
        lon         = site.lon,
        n_legs      = site.n_legs,
        lane_config = site.lane_config,
        source      = args.geometry,
        cache_path  = str(OSM_CACHE),
    )
    sd["geometry"] = geom
    print(f"  Geometry: {geom.notes or 'OK'}")
    leg_idxs = [leg.leg_idx for leg in geom.legs]

    # 2. Volumes
    if site_counts:
        try:
            tm = observed_turning_movements(site.site_id, leg_idxs, site_counts)
        except ValueError as e:
            print(f"  Counts error: {e}")
            sd["notes"] = str(e)
            return sd
    else:
        tm = generate_turning_movements(
            site_id     = site.site_id,
            n_legs      = site.n_legs,
            leg_idxs    = leg_idxs,
            is_ramp     = site.is_ramp,
            route1      = site.route1,
            pm1         = site.pm1,
            route2      = site.route2,
            pm2         = site.pm2,
            district    = site.district,
            county      = site.county,
            aadt_lookup = aadt_lookup,
            scenario    = args.scenario,
            hv_pct      = args.hv_pct,
            k_factor    = args.k_factor,
            d_factor    = args.d_factor,
            cross_ratio = args.cross_ratio,
        )
    sd["turning_movements"] = tm
    print(f"  Volumes: {tm.aadt_source}; modeled entry demand "
          f"{tm.total_entry} veh/h")

    if not sidra_available:
        print("  Skipping SIDRA processing (API unavailable).")
        return sd

    sipx_path = str(SITES_DIR / f"{site.site_id}.sipx")
    try:
        _run_sidra(site, geom, tm, sipx_path, args, model, target, sd)
    except Exception as e:
        print(f"  SIDRA error: {e}")
        sd["notes"] = str(e)
    return sd


def _run_sidra(site: Site, geom, tm, sipx_path: str,
               args: argparse.Namespace, model: dict, target, sd: dict):
    from sidra_api import SIDRASession

    with SIDRASession() as sid:
        sid.create_project(sipx_path, site.location)
        s = sid.add_roundabout_site_from_template(site.location)

        for leg in geom.legs:
            sid.configure_leg(
                site              = s,
                leg_orientation   = leg.leg_idx,
                n_entry_lanes     = leg.n_entry_lanes,
                n_exit_lanes      = leg.n_exit_lanes,
                n_circ_lanes      = leg.n_circ_lanes,
                circ_width_m      = leg.circulating_width_m,
                island_diameter_m = leg.island_diameter_m,
                entry_width_m     = leg.entry_width_m,
                entry_radius_m    = leg.entry_radius_m,
                entry_angle_deg   = leg.entry_angle_deg,
                leg_name          = leg.leg_name,
            )
        sid.finalize_geometry(s)

        for (orig, dest), (lv, hv) in tm.volumes.items():
            sid.set_volume(s, orig, dest, lv, hv)

        sid.set_capacity_model(s, model["code"])
        print(f"  SIDRA site: {s.ModelName}, capacity model {model['label']}")

        def run_at(value: float) -> list[dict]:
            sid.set_calibration_parameter(s, value)
            sid.process_site(s)
            return sid.read_lane_outputs(s)

        def mean(xs):
            xs = [x for x in xs if x is not None]
            return sum(xs) / len(xs) if xs else None

        # Baseline and +/- 0.1 points for the summary
        default = model["default"]
        sd["lane_outputs"] = run_at(default)
        for key, v in (("minus", default - 0.1), ("default", default),
                       ("plus", default + 0.1)):
            outs = sd["lane_outputs"] if key == "default" else run_at(v)
            sd["key_points"][key] = {
                "value": round(v, 3),
                "capacity": mean([o["capacity_veh_h"] for o in outs
                                  if o["capacity_veh_h"] > 0]),
                "delay": mean([o["avg_delay_s"] for o in outs]),
            }
        print(f"  Baseline processed. {len(sd['lane_outputs'])} lanes.")

        def model_fn_sweep(value: float) -> dict:
            outs = run_at(value)
            return {
                "capacities": [o["capacity_veh_h"] for o in outs],
                "deg_satns":  [o["deg_satn"] for o in outs],
                "avg_delays": [o["avg_delay_s"] for o in outs],
            }

        print(f"  Running sensitivity sweep ({args.steps} steps) ...")
        sd["sensitivity"] = sensitivity_sweep(
            site_id  = site.site_id,
            model_fn = model_fn_sweep,
            param    = model["param"],
            p_min    = model["p_min"],
            p_max    = model["p_max"],
            n_steps  = args.steps,
        )

        save_value = default
        if target:
            legs = {leg for leg, _ in target if leg is not None}
            observed_cap = sum(c for _, c in target) / len(target)

            def model_fn_cal(value: float) -> float:
                outs = run_at(value)
                caps = [o["capacity_veh_h"] for o in outs
                        if o["capacity_veh_h"] > 0
                        and (not legs or o["leg_idx"] in legs)]
                return sum(caps) / len(caps) if caps else 0.0

            cal = calibrate_bisection(
                site_id           = site.site_id,
                model_fn          = model_fn_cal,
                observed_capacity = observed_cap,
                param             = model["param"],
                p_min             = model["p_min"],
                p_max             = model["p_max"],
            )
            if legs:
                cal.notes = (cal.notes + " Observed legs: " + ", ".join(
                    ORIENTATION_LABELS[l] for l in sorted(legs))).strip()
            sd["calibration"] = cal
            if cal.value == cal.value:      # not NaN
                save_value = cal.value
            print(f"  Calibrated {model['param']} = {cal.value:.3f} "
                  f"(error {cal.error_pct:.1f}%)")

        # Save the project at the calibrated value (or the default)
        run_at(save_value)
        sid.save_project()
        sd["saved_value"] = round(save_value, 4)
        print(f"  Saved {Path(sipx_path).name} at {model['param']} = {save_value:.3f}")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
