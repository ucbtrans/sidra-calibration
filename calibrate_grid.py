#!/usr/bin/env python3
"""
calibrate_grid.py  -  2D grid search calibration over two user-selected parameters.

Phase 2 of the Task 5 calibration tool.

Usage:
    python calibrate_grid.py configs/example_grid.yaml

The YAML config specifies:
  - Site geometry and model (same as calibrate_site.py)
  - grid_search.parameter_1 and grid_search.parameter_2
    (any two parameters from param_registry.PARAM_REGISTRY)
  - Observed targets and weights

Outputs:
  output/calibration/{site_id}/grid_{p1}_{p2}/
    grid_results.json  -  full error surface
    heatmap.png        -  2D error heatmap with best-fit marker

Run count = len(p1_values) * len(p2_values).
Keep n_steps <= 15 per parameter to stay under ~225 SIDRA runs.
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
from multi_target import TARGET_KEYS, TARGET_LABELS, DEFAULT_WEIGHTS
from param_registry import PARAM_REGISTRY, get_param_values, validate_param
from grid_search import grid_search_2d, GridSearchResult

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# ---------------------------------------------------------------------------
# Paths and model registry
# ---------------------------------------------------------------------------
ROOT     = Path(__file__).parent.parent
TEMPLATE = ROOT / "template_hcm6.sipx"
OUT_BASE = Path(__file__).parent / "output" / "calibration"

MODELS = {
    "sidra_standard_us": {"code": 0, "label": "SIDRA Standard US"},
    "hcm2010":           {"code": 1, "label": "HCM 2010"},
    "hcm6":              {"code": 2, "label": "HCM 6"},
}

HCM6_LEGS = [0, 2, 3, 6]
GREY  = "#303030"
LGREY = "#D0D0D0"
DPI   = 200


# ---------------------------------------------------------------------------
# SIDRA helpers (same pattern as calibrate_site.py)
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


def _set_geometry(sid, site, icd_m, circ_lanes):
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


def _set_volumes(sid, site, lv, hv):
    for orig in HCM6_LEGS:
        for dest in HCM6_LEGS:
            if orig != dest:
                try:
                    sid.set_volume(site, orig, dest, lv, hv)
                except Exception:
                    pass


def _read_site_outputs(outputs):
    caps = [o["capacity_veh_h"] for o in outputs
            if o.get("capacity_veh_h", 0) > 0]
    seen = set()
    delays, queues = [], []
    for o in outputs:
        li = o["leg_idx"]
        if li not in seen:
            seen.add(li)
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
def print_report(cfg, result):
    m_label = MODELS[cfg["model"]]["label"]
    p1_label = PARAM_REGISTRY[result.param1_name]["label"]
    p2_label = PARAM_REGISTRY[result.param2_name]["label"]
    sep = "=" * 65

    print()
    print(sep)
    print(f"  Site:        {result.site_id}")
    if cfg.get("description"):
        print(f"  Info:        {cfg['description']}")
    print(f"  Model:       {m_label}")
    print(f"  Parameter 1: {p1_label}")
    print(f"  Parameter 2: {p2_label}")
    print(f"  Grid size:   {len(result.p1_values)} x {len(result.p2_values)}"
          f" = {result.n_runs} SIDRA runs")
    print(sep)

    if result.targets:
        print("  Observed targets:")
        for k, v in result.targets.items():
            w = result.weights.get(k, 0)
            lbl = TARGET_LABELS.get(k, k)
            print(f"    {lbl:42s} {v:8.2f}   weight={w:.1f}")
        print()
        print(f"  Best-fit {result.param1_name}:  {result.best_p1}")
        print(f"  Best-fit {result.param2_name}:  {result.best_p2}")
        print(f"  Minimum weighted error:   {result.best_error:.6f}")
        print()
        print("  Residuals at best-fit combination:")
        for k, pct in result.residuals.items():
            lbl = TARGET_LABELS.get(k, k)
            flag = "  OK" if abs(pct) <= 5 else "  !! > 5%"
            print(f"    {lbl:42s} {pct:+7.1f}%{flag}")
    else:
        print("  Mode: sensitivity grid only (no targets specified).")

    if result.notes:
        print()
        for line in result.notes.strip().splitlines():
            print(f"  Note: {line}")
    print(sep)
    print()


# ---------------------------------------------------------------------------
# Heatmap plot
# ---------------------------------------------------------------------------
def save_heatmap(cfg, result, p1_info, p2_info, out_dir):
    plt.rcParams.update({
        "font.family": "Arial", "font.size": 9,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.labelcolor": GREY, "xtick.color": GREY, "ytick.color": GREY,
    })

    p1v = result.p1_values
    p2v = result.p2_values
    n1, n2 = len(p1v), len(p2v)

    # Build error matrix (rows=p2, cols=p1 for imshow convention)
    err_mat = np.full((n2, n1), np.nan)
    cap_mat = np.full((n2, n1), np.nan)

    for row in result.grid:
        try:
            i1 = p1v.index(row[result.param1_name])
            i2 = p2v.index(row[result.param2_name])
            if row.get("error") is not None:
                err_mat[i2, i1] = row["error"]
            if row.get("capacity_veh_h") is not None:
                cap_mat[i2, i1] = row["capacity_veh_h"]
        except (ValueError, KeyError):
            pass

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    fig.patch.set_facecolor("white")

    # --- Panel A: error heatmap ---
    ax = axes[0]
    im = ax.imshow(err_mat, origin="lower", aspect="auto",
                   cmap="RdYlGn_r", interpolation="nearest")
    plt.colorbar(im, ax=ax, label="Weighted error")

    # Axis tick labels
    ax.set_xticks(range(n1))
    ax.set_yticks(range(n2))
    ax.set_xticklabels(
        [_fmt_val(v, p1_info) for v in p1v], rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(
        [_fmt_val(v, p2_info) for v in p2v], fontsize=8)

    # Best-fit marker
    if not np.isnan(result.best_p1):
        try:
            xi = p1v.index(result.best_p1)
            yi = p2v.index(result.best_p2)
            ax.plot(xi, yi, "*", color="white", ms=14, markeredgecolor="black",
                    markeredgewidth=0.8, zorder=5,
                    label=f"Best: {result.param1_name}={result.best_p1}, "
                          f"{result.param2_name}={result.best_p2}")
            ax.legend(fontsize=7.5, loc="upper right", framealpha=0.9)
        except ValueError:
            pass

    ax.set_xlabel(PARAM_REGISTRY[result.param1_name]["label"], fontsize=9)
    ax.set_ylabel(PARAM_REGISTRY[result.param2_name]["label"], fontsize=9)
    ax.set_title(
        f"A. Weighted error surface\n{result.site_id}",
        fontsize=9, fontweight="bold", color=GREY)

    # --- Panel B: capacity heatmap ---
    ax2 = axes[1]
    im2 = ax2.imshow(cap_mat, origin="lower", aspect="auto",
                     cmap="Blues", interpolation="nearest")
    plt.colorbar(im2, ax=ax2, label="Mean entry capacity (veh/h)")

    ax2.set_xticks(range(n1))
    ax2.set_yticks(range(n2))
    ax2.set_xticklabels(
        [_fmt_val(v, p1_info) for v in p1v], rotation=45, ha="right", fontsize=8)
    ax2.set_yticklabels(
        [_fmt_val(v, p2_info) for v in p2v], fontsize=8)

    if not np.isnan(result.best_p1):
        try:
            xi = p1v.index(result.best_p1)
            yi = p2v.index(result.best_p2)
            ax2.plot(xi, yi, "*", color="white", ms=14,
                     markeredgecolor="black", markeredgewidth=0.8, zorder=5)
        except ValueError:
            pass

    # Target capacity reference line (if available)
    if "capacity_veh_h" in result.targets:
        t_cap = result.targets["capacity_veh_h"]
        # Find cells closest to target and draw a contour-like annotation
        ax2.set_title(
            f"B. Entry capacity surface\n(target = {t_cap:.0f} veh/h)",
            fontsize=9, fontweight="bold", color=GREY)
    else:
        ax2.set_title("B. Entry capacity surface",
                      fontsize=9, fontweight="bold", color=GREY)

    ax2.set_xlabel(PARAM_REGISTRY[result.param1_name]["label"], fontsize=9)
    ax2.set_ylabel(PARAM_REGISTRY[result.param2_name]["label"], fontsize=9)

    model_label = MODELS[cfg["model"]]["label"]
    fig.suptitle(
        f"Grid Search  -  {result.site_id}  -  {model_label}  -  "
        f"{result.param1_name} x {result.param2_name}",
        fontsize=10, fontweight="bold", color="#1F4E79", y=1.02,
    )
    fig.tight_layout()

    plot_path = out_dir / "heatmap.png"
    fig.savefig(plot_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Heatmap saved: {plot_path}")


def _fmt_val(v, param_info):
    """Format a parameter value for axis tick labels."""
    if param_info["type"] == "categorical":
        labels = param_info.get("value_labels", [])
        try:
            return labels[param_info["values"].index(v)]
        except (ValueError, IndexError):
            return str(v)
    return f"{v:.3g}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="2D grid search calibration over two user-selected parameters.")
    parser.add_argument("config", help="Path to YAML config file")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"Config not found: {cfg_path}")
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

    # --- Validate parameters ---
    gs_cfg = cfg.get("grid_search", {})
    p1_cfg = gs_cfg.get("parameter_1", {})
    p2_cfg = gs_cfg.get("parameter_2", {})
    p1_name = p1_cfg.get("name")
    p2_name = p2_cfg.get("name")

    if not p1_name or not p2_name:
        print("grid_search.parameter_1.name and parameter_2.name must be specified.")
        sys.exit(1)
    if p1_name == p2_name:
        print("parameter_1 and parameter_2 must be different.")
        sys.exit(1)

    for pname in (p1_name, p2_name):
        err = validate_param(pname, model_key)
        if err:
            print(f"Parameter error: {err}")
            sys.exit(1)

    p1_info = PARAM_REGISTRY[p1_name]
    p2_info = PARAM_REGISTRY[p2_name]
    p1_values = get_param_values(p1_name, p1_cfg)
    p2_values = get_param_values(p2_name, p2_cfg)

    # --- Targets and weights ---
    raw_targets = cfg.get("targets", {}) or {}
    targets = {k: float(v) for k, v in raw_targets.items()
               if v is not None and k in TARGET_KEYS}

    raw_weights = cfg.get("weights", {}) or {}
    weights = {**DEFAULT_WEIGHTS,
               **{k: float(v) for k, v in raw_weights.items()}}

    # --- Geometry and volumes ---
    geo        = cfg.get("geometry", {})
    icd_m      = float(geo.get("icd_m", 20.0))
    circ_lanes = int(geo.get("circ_lanes", 1))
    vol_cfg    = cfg.get("volumes", {}) or {}
    lv         = int(vol_cfg.get("lv_per_movement", 23))
    hv_pct     = float(vol_cfg.get("hv_pct", 0.06))
    hv         = max(1, round(lv * hv_pct))

    site_id = cfg.get("site_id", "UNKNOWN_SITE")
    out_dir = OUT_BASE / site_id / f"grid_{p1_name}_{p2_name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    work = out_dir / f"_work_{site_id}.sipx"
    shutil.copy2(str(TEMPLATE), str(work))

    n_runs = len(p1_values) * len(p2_values)
    print(f"\nSite:        {site_id}")
    if cfg.get("description"):
        print(f"Info:        {cfg['description']}")
    print(f"Model:       {model_info['label']}")
    print(f"Parameter 1: {p1_info['label']}  ({len(p1_values)} values)")
    print(f"Parameter 2: {p2_info['label']}  ({len(p2_values)} values)")
    print(f"Grid size:   {len(p1_values)} x {len(p2_values)} = {n_runs} SIDRA runs")
    if targets:
        print(f"Targets:     {targets}")
    print()

    result = None
    p1_setter = p1_info["setter"]
    p2_setter = p2_info["setter"]

    try:
        with SIDRASession() as sid:
            sid.open_project(str(work))
            site = _get_us_roundabout_site(sid)
            site.ModelSetting.Rou_Capacity_Model = mcode
            _set_geometry(sid, site, icd_m, circ_lanes)
            _set_volumes(sid, site, lv, hv)

            def model_fn(p1, p2):
                p1_setter(sid, site, mcode, p1)
                p2_setter(sid, site, mcode, p2)
                sid.process_site(site)
                raw = sid.read_lane_outputs(site)
                return _read_site_outputs(raw)

            result = grid_search_2d(
                site_id   = site_id,
                model_fn  = model_fn,
                p1_values = p1_values,
                p2_values = p2_values,
                p1_name   = p1_name,
                p2_name   = p2_name,
                targets   = targets,
                weights   = weights,
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

    results_path = out_dir / "grid_results.json"
    results_path.write_text(
        json.dumps(dataclasses.asdict(result), indent=2), encoding="utf-8"
    )
    print(f"Results saved: {results_path}")

    save_heatmap(cfg, result, p1_info, p2_info, out_dir)


if __name__ == "__main__":
    main()
