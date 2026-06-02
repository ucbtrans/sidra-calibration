#!/usr/bin/env python3
"""
calibrate_site.py  -  Single-parameter multi-target SIDRA calibration.

Phase 1 of the Task 5 calibration tool.

Usage:
    python calibrate_site.py configs/example_site.yaml
    python calibrate_site.py configs/D03_site.yaml --plot

Reads a YAML config specifying:
  - Site geometry (ICD, circulating lanes)
  - Model (sidra_standard_us | hcm2010 | hcm6)
  - Observed target values (capacity, Q95, delay) with weights
  - Sweep range and step count

Finds the parameter value (fe or cf) that minimizes weighted normalized
error across all specified targets. Saves results JSON and sweep plot.

If no targets are specified, runs a pure sensitivity sweep and reports
the full output curve - useful before field data is available.
"""

import sys, json, shutil, gc, io, argparse, dataclasses
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

import numpy as np

try:
    import yaml
except ImportError:
    print("PyYAML required:  pip install pyyaml")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent / "src"))
from sidra_api import SIDRASession
from multi_target import (
    calibrate_multi_target, MultiTargetResult,
    TARGET_KEYS, TARGET_LABELS, DEFAULT_WEIGHTS,
)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT     = Path(__file__).parent.parent
TEMPLATE = ROOT / "template_hcm6.sipx"
OUT_BASE = Path(__file__).parent / "output" / "calibration"

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------
MODELS = {
    "sidra_standard_us": {
        "code":  0, "param": "fe", "label": "SIDRA Standard US",
        "p_min": 0.5, "p_max": 2.0,
    },
    "hcm2010": {
        "code":  1, "param": "cf", "label": "HCM 2010",
        "p_min": 0.7, "p_max": 1.3,
    },
    "hcm6": {
        "code":  2, "param": "cf", "label": "HCM 6",
        "p_min": 0.7, "p_max": 1.3,
    },
}

# Leg orientations used in the US RHD template
HCM6_LEGS = [0, 2, 3, 6]

# Plot styling
GREY      = "#303030"
LGREY     = "#D0D0D0"
C_CAP     = "#1F4E79"   # capacity curve color
C_Q95     = "#C55A11"   # Q95 curve color
C_DELAY   = "#375623"   # delay curve color
C_ERROR   = "#1F4E79"   # error curve color
C_BEST    = "#C55A11"   # best-fit marker color
DPI       = 200

TARGET_COLORS = {
    "capacity_veh_h": C_CAP,
    "q95_veh":        C_Q95,
    "delay_s":        C_DELAY,
}


# ---------------------------------------------------------------------------
# SIDRA helpers
# ---------------------------------------------------------------------------
def _get_us_roundabout_site(sid):
    proj = sid._project
    for fi in range(proj.SiteFolders.Count):
        folder = proj.SiteFolders[fi]
        for si in range(folder.Sites.Count):
            s = folder.Sites[si]
            if "Roundabout" in s.Name and not s.Driveonleft:
                return s
    raise RuntimeError("US roundabout site not found in template.")


def _set_model(site, model_code: int):
    site.ModelSetting.Rou_Capacity_Model = model_code


def _set_calibration_param(sid, site, model_code: int, value: float):
    for leg_idx in range(8):
        leg = sid._get_leg(site, leg_idx)
        if leg is None:
            continue
        rleg = leg.Leg_roundabout
        try:
            if model_code == 0:
                rleg.Environment_factor = value
            elif model_code == 1:
                rleg.LegRouHCM2010.Model_calib_factor = value
            elif model_code == 2:
                rleg.LegRouHCM6.Model_calib_factor = value
        except Exception:
            pass


def _set_geometry(sid, site, icd_m: float, circ_lanes: int):
    for leg_idx in range(8):
        leg = sid._get_leg(site, leg_idx)
        if leg is None:
            continue
        rleg = leg.Leg_roundabout
        try:
            rleg.Island_diameter       = float(icd_m)
            rleg.Num_circulating_lanes = int(circ_lanes)
        except Exception:
            pass


def _set_volumes(sid, site, lv: int, hv: int):
    for orig in HCM6_LEGS:
        for dest in HCM6_LEGS:
            if orig != dest:
                try:
                    sid.set_volume(site, orig, dest, lv, hv)
                except Exception:
                    pass


def _read_site_outputs(outputs: list) -> dict:
    """
    Aggregate per-lane SIDRA outputs to site-level metrics.

    Capacity: mean across all entry lanes with positive capacity.
    Q95 and Delay: leg-level (de-duplicated by leg_idx), then averaged.
    """
    caps = [o["capacity_veh_h"] for o in outputs
            if o.get("capacity_veh_h", 0) > 0]

    seen_legs = set()
    delays, queues = [], []
    for o in outputs:
        li = o["leg_idx"]
        if li not in seen_legs:
            seen_legs.add(li)
            d = o.get("avg_delay_s")
            q = o.get("queue_95pct_veh")
            if d is not None:
                delays.append(float(d))
            if q is not None:
                queues.append(float(q))

    return {
        "capacity_veh_h": float(np.mean(caps))   if caps   else 0.0,
        "q95_veh":        float(np.mean(queues))  if queues else 0.0,
        "delay_s":        float(np.mean(delays))  if delays else 0.0,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_report(cfg: dict, result: MultiTargetResult):
    model_label = MODELS[cfg["model"]]["label"]
    sep = "=" * 62
    print()
    print(sep)
    print(f"  Site:      {result.site_id}")
    if cfg.get("description"):
        print(f"  Info:      {cfg['description']}")
    print(f"  Model:     {model_label}")
    print(f"  Parameter: {result.parameter}")
    print(sep)

    if result.targets:
        print("  Observed targets:")
        for k, v in result.targets.items():
            w = result.weights.get(k, 0)
            lbl = TARGET_LABELS.get(k, k)
            print(f"    {lbl:42s} {v:8.2f}   weight={w:.1f}")
        print()
        print(f"  Best-fit {result.parameter}:           {result.best_value:.4f}")
        print(f"  Combined weighted error:   {result.best_error:.6f}")
        print()
        print("  Residuals at best-fit value:")
        for k, pct in result.residuals.items():
            lbl = TARGET_LABELS.get(k, k)
            flag = "  OK" if abs(pct) <= 5 else "  !! > 5%"
            print(f"    {lbl:42s} {pct:+7.1f}%{flag}")
    else:
        print("  Mode: sensitivity sweep only (no targets specified).")
        print("  Specify targets in YAML to get a best-fit parameter value.")

    if result.notes:
        print()
        print("  Notes:")
        for line in result.notes.strip().splitlines():
            print(f"    {line}")
    print(sep)
    print()


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------
def save_plot(cfg: dict, result: MultiTargetResult, out_dir: Path,
              show: bool = False):
    plt.rcParams.update({
        "font.family": "Arial", "font.size": 9,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.labelcolor": GREY, "xtick.color": GREY, "ytick.color": GREY,
    })

    valid_rows = [r for r in result.sweep if r.get("error") is not None
                  or r.get("capacity_veh_h") is not None]
    xs = [r["param_value"] for r in valid_rows]

    has_targets = bool(result.targets)
    fig, axes = plt.subplots(1, 2 if has_targets else 1,
                              figsize=(12 if has_targets else 7, 5))
    fig.patch.set_facecolor("white")
    if not has_targets:
        axes = [axes]

    # Panel A - absolute model output values vs parameter
    ax = axes[0]
    for key in TARGET_KEYS:
        ys = [r.get(key) for r in valid_rows]
        if not any(v is not None and v > 0 for v in ys):
            continue
        col = TARGET_COLORS.get(key, GREY)
        lbl = TARGET_LABELS.get(key, key)
        ax.plot(xs, ys, "-o", color=col, lw=1.8, ms=3.5, label=lbl)
        if key in result.targets and result.targets[key]:
            ax.axhline(result.targets[key], color=col, lw=0.9,
                       ls="--", alpha=0.65,
                       label=f"{lbl.split('(')[0].strip()} target")

    if not np.isnan(result.best_value):
        ax.axvline(result.best_value, color=GREY, lw=1.0, ls="--", alpha=0.7,
                   label=f"Best {result.parameter} = {result.best_value:.3f}")

    ax.set_xlabel(f"Parameter value  ({result.parameter})", fontsize=9)
    ax.set_ylabel("Model output", fontsize=9)
    ax.set_title(
        f"A. Model outputs vs {result.parameter}\n{result.site_id}",
        fontsize=9, fontweight="bold", color=GREY)
    ax.legend(fontsize=7.5, framealpha=0.9)
    ax.grid(True, axis="y", color=LGREY, lw=0.4)

    # Panel B - combined weighted error curve
    if has_targets:
        ax2 = axes[1]
        errs = [r.get("error") for r in valid_rows]
        ax2.plot(xs, errs, "-o", color=C_ERROR, lw=2.0, ms=3.5,
                 label="Weighted error")

        if not np.isnan(result.best_value):
            ax2.plot(result.best_value, result.best_error, "*",
                     color=C_BEST, ms=12, zorder=5,
                     label=f"Minimum at {result.parameter} = {result.best_value:.3f}")
            ax2.axvline(result.best_value, color=GREY, lw=1.0, ls="--", alpha=0.7)

        w = result.weights
        ax2.set_xlabel(f"Parameter value  ({result.parameter})", fontsize=9)
        ax2.set_ylabel("Weighted normalized error", fontsize=9)
        ax2.set_title(
            f"B. Combined weighted error vs {result.parameter}\n"
            f"Weights: C = {w.get('capacity_veh_h', 0):.1f}  "
            f"Q95 = {w.get('q95_veh', 0):.1f}  "
            f"d = {w.get('delay_s', 0):.1f}",
            fontsize=9, fontweight="bold", color=GREY)
        ax2.legend(fontsize=7.5, framealpha=0.9)
        ax2.grid(True, axis="y", color=LGREY, lw=0.4)

    model_label = MODELS[cfg["model"]]["label"]
    fig.suptitle(
        f"Calibration Sweep  -  {result.site_id}  -  {model_label}",
        fontsize=10, fontweight="bold", color="#1F4E79", y=1.01,
    )
    fig.tight_layout()

    plot_path = out_dir / "sweep_plot.png"
    fig.savefig(plot_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved:    {plot_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Single-parameter multi-target SIDRA calibration (Phase 1).")
    parser.add_argument("config", help="Path to YAML config file")
    parser.add_argument("--plot", action="store_true",
                        help="Save sweep plot (always saved; flag reserved for display)")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"Config file not found: {cfg_path}")
        sys.exit(1)

    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # --- Validate model ---
    model_key = cfg.get("model", "sidra_standard_us")
    if model_key not in MODELS:
        print(f"Unknown model '{model_key}'. Choose from: {list(MODELS)}")
        sys.exit(1)
    model_info = MODELS[model_key]
    mcode = model_info["code"]
    param = model_info["param"]

    # --- Sweep settings ---
    sweep_cfg = cfg.get("sweep", {})
    p_min   = float(sweep_cfg.get("p_min",   model_info["p_min"]))
    p_max   = float(sweep_cfg.get("p_max",   model_info["p_max"]))
    n_steps = int(sweep_cfg.get("n_steps", 30))

    # --- Targets and weights ---
    raw_targets = cfg.get("targets", {}) or {}
    targets = {k: float(v) for k, v in raw_targets.items()
               if v is not None and k in TARGET_KEYS}

    raw_weights = cfg.get("weights", {}) or {}
    weights = {**DEFAULT_WEIGHTS,
               **{k: float(v) for k, v in raw_weights.items()}}

    # --- Geometry ---
    geo        = cfg.get("geometry", {})
    icd_m      = float(geo.get("icd_m", 20.0))
    circ_lanes = int(geo.get("circ_lanes", 1))

    # --- Volumes ---
    vol_cfg = cfg.get("volumes", {}) or {}
    lv      = int(vol_cfg.get("lv_per_movement", 23))
    hv_pct  = float(vol_cfg.get("hv_pct", 0.06))
    hv      = max(1, round(lv * hv_pct))

    site_id = cfg.get("site_id", "UNKNOWN_SITE")
    out_dir = OUT_BASE / site_id
    out_dir.mkdir(parents=True, exist_ok=True)

    work = out_dir / f"_work_{site_id}.sipx"
    shutil.copy2(str(TEMPLATE), str(work))

    # --- Console summary ---
    print(f"\nSite:      {site_id}")
    if cfg.get("description"):
        print(f"Info:      {cfg['description']}")
    print(f"Model:     {model_info['label']}  ({param} in [{p_min}, {p_max}],"
          f" {n_steps} steps)")
    print(f"Geometry:  ICD={icd_m} m  circ_lanes={circ_lanes}")
    print(f"Volumes:   lv={lv}  hv={hv} per movement")
    if targets:
        print(f"Targets:   {targets}")
    else:
        print("Targets:   none (sensitivity sweep mode)")
    print()

    result = None
    try:
        with SIDRASession() as sid:
            sid.open_project(str(work))
            site = _get_us_roundabout_site(sid)
            _set_model(site, mcode)
            _set_geometry(sid, site, icd_m, circ_lanes)
            _set_volumes(sid, site, lv, hv)

            def model_fn(p: float) -> dict:
                _set_calibration_param(sid, site, mcode, p)
                sid.process_site(site)
                raw = sid.read_lane_outputs(site)
                return _read_site_outputs(raw)

            result = calibrate_multi_target(
                site_id  = site_id,
                model_fn = model_fn,
                targets  = targets,
                weights  = weights,
                param    = param,
                p_min    = p_min,
                p_max    = p_max,
                n_steps  = n_steps,
            )

    except Exception as exc:
        print(f"ERROR: SIDRA session failed: {exc}")
        sys.exit(1)
    finally:
        try:
            work.unlink()
        except Exception:
            pass
        gc.collect()

    print_report(cfg, result)

    results_path = out_dir / "results.json"
    results_path.write_text(
        json.dumps(dataclasses.asdict(result), indent=2), encoding="utf-8"
    )
    print(f"Results saved: {results_path}")

    save_plot(cfg, result, out_dir)


if __name__ == "__main__":
    main()
