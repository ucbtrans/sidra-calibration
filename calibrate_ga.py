#!/usr/bin/env python3
"""
calibrate_ga.py  -  Genetic-algorithm calibration over three or more parameters.

Phase 3 of the Task 5 calibration tool.

Usage:
    python calibrate_ga.py configs/example_ga.yaml

The YAML config specifies:
  - Site geometry and model (same as calibrate_site.py / calibrate_grid.py)
  - genetic_algorithm.parameters: a list of two or more parameters to calibrate
    (any parameters from param_registry.PARAM_REGISTRY)
  - genetic_algorithm.settings: GA hyperparameters (optional; sensible defaults)
  - Observed targets and weights

Outputs:
  output/calibration/{site_id}/ga_{p1}_{p2}_.../
    ga_results.json   -  best parameters, residuals, convergence history
    convergence.png   -  best/mean weighted error vs generation, residual bars

Use the GA when there are three or more parameters (a full grid is then
exponential). For one or two parameters prefer calibrate_site.py or
calibrate_grid.py, which enumerate the space exactly.

The GA engine (src/genetic_search.py) is self-contained: no third-party
library is required to run a calibration.
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
from param_registry import (
    PARAM_REGISTRY, get_param_spec, validate_param,
)
from genetic_search import genetic_search, GAResult

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
GREY   = "#303030"
LGREY  = "#D0D0D0"
C_BEST = "#1F4E79"
C_MEAN = "#C55A11"
DPI    = 200


# ---------------------------------------------------------------------------
# SIDRA helpers (same pattern as calibrate_grid.py)
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


def _fmt_param(name, value):
    """Human-readable parameter value (categorical labels where applicable)."""
    info = PARAM_REGISTRY[name]
    if info["type"] == "categorical":
        try:
            return info["value_labels"][info["values"].index(value)]
        except (ValueError, IndexError, KeyError):
            return str(value)
    return f"{float(value):.4f}"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_report(cfg, result: GAResult):
    m_label = MODELS[cfg["model"]]["label"]
    sep = "=" * 65
    print()
    print(sep)
    print(f"  Site:      {result.site_id}")
    if cfg.get("description"):
        print(f"  Info:      {cfg['description']}")
    print(f"  Model:     {m_label}")
    print(f"  Method:    Genetic algorithm ({len(result.param_names)} parameters)")
    s = result.settings
    print(f"  GA budget: pop={s['pop_size']}  gen<={s['n_gen']}  "
          f"seed={s['seed']}")
    print(f"  SIDRA runs: {result.n_evals} distinct "
          f"({result.n_requests} fitness lookups, "
          f"{result.n_requests - result.n_evals} served from cache)")
    print(sep)

    if not result.targets:
        print("  No targets specified - nothing to calibrate.")
        print(sep); print()
        return

    print("  Observed targets:")
    for k, v in result.targets.items():
        w = result.weights.get(k, 0)
        lbl = TARGET_LABELS.get(k, k)
        print(f"    {lbl:42s} {v:8.2f}   weight={w:.1f}")
    print()
    print("  Best-fit parameters:")
    for name in result.param_names:
        val = result.best_params.get(name)
        print(f"    {PARAM_REGISTRY[name]['label']:42s} {_fmt_param(name, val)}")
    print()
    print(f"  Minimum weighted error:   {result.best_error:.6f}")
    print(f"  Converged:                {result.converged}")
    print()
    print("  Residuals at best-fit combination:")
    for k, pct in result.residuals.items():
        lbl = TARGET_LABELS.get(k, k)
        flag = "  OK" if abs(pct) <= 5 else "  !! > 5%"
        print(f"    {lbl:42s} {pct:+7.1f}%{flag}")

    if result.notes:
        print()
        for line in result.notes.strip().splitlines():
            print(f"  Note: {line}")
    print(sep)
    print()


# ---------------------------------------------------------------------------
# Convergence + residual plot
# ---------------------------------------------------------------------------
def save_plot(cfg, result: GAResult, out_dir: Path):
    plt.rcParams.update({
        "font.family": "Arial", "font.size": 9,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.labelcolor": GREY, "xtick.color": GREY, "ytick.color": GREY,
    })

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.patch.set_facecolor("white")

    # Panel A - convergence
    ax = axes[0]
    gens = [h["gen"] for h in result.history]
    best = [h["best_error"] for h in result.history]
    mean = [h["mean_error"] for h in result.history]
    ax.plot(gens, best, "-o", color=C_BEST, lw=2.0, ms=3.5, label="Best error")
    if any(m is not None for m in mean):
        ax.plot(gens, [m if m is not None else np.nan for m in mean],
                "-s", color=C_MEAN, lw=1.3, ms=3.0, alpha=0.8,
                label="Population mean")
    ax.set_xlabel("Generation", fontsize=9)
    ax.set_ylabel("Weighted normalized error", fontsize=9)
    ax.set_title(f"A. GA convergence\n{result.site_id}",
                 fontsize=9, fontweight="bold", color=GREY)
    ax.legend(fontsize=8, framealpha=0.9)
    ax.grid(True, axis="y", color=LGREY, lw=0.4)

    # Panel B - residuals at best fit
    ax2 = axes[1]
    keys = [k for k in TARGET_KEYS if k in result.residuals]
    vals = [result.residuals[k] for k in keys]
    labels = [TARGET_LABELS.get(k, k).split("(")[0].strip() for k in keys]
    colors = ["#2E7D32" if abs(v) <= 5 else "#C0392B" for v in vals]
    ypos = range(len(keys))
    ax2.barh(list(ypos), vals, color=colors, height=0.55)
    ax2.axvline(0, color=GREY, lw=0.8)
    ax2.axvline(5,  color=LGREY, lw=0.8, ls="--")
    ax2.axvline(-5, color=LGREY, lw=0.8, ls="--")
    ax2.set_yticks(list(ypos))
    ax2.set_yticklabels(labels, fontsize=8)
    ax2.set_xlabel("Residual at best fit (%)", fontsize=9)
    ax2.set_title("B. Per-target residuals\n(dashed lines = +/- 5%)",
                  fontsize=9, fontweight="bold", color=GREY)
    for i, v in zip(ypos, vals):
        ax2.text(v + (0.4 if v >= 0 else -0.4), i, f"{v:+.1f}%",
                 va="center", ha="left" if v >= 0 else "right", fontsize=8)
    ax2.grid(True, axis="x", color=LGREY, lw=0.4)

    pstr = ", ".join(f"{n}={_fmt_param(n, result.best_params.get(n))}"
                     for n in result.param_names)
    model_label = MODELS[cfg["model"]]["label"]
    fig.suptitle(
        f"GA Calibration  -  {result.site_id}  -  {model_label}\nBest: {pstr}",
        fontsize=10, fontweight="bold", color="#1F4E79", y=1.04)
    fig.tight_layout()

    plot_path = out_dir / "convergence.png"
    fig.savefig(plot_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved:    {plot_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Genetic-algorithm calibration over 3+ parameters (Phase 3).")
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

    # --- Parameters to calibrate ---
    ga_cfg     = cfg.get("genetic_algorithm", {}) or {}
    param_list = ga_cfg.get("parameters", []) or []
    if len(param_list) < 2:
        print("genetic_algorithm.parameters must list at least two parameters.")
        print("For one parameter use calibrate_site.py; for two, calibrate_grid.py.")
        sys.exit(1)

    names = [p.get("name") for p in param_list]
    if len(set(names)) != len(names):
        print("Duplicate parameter names in genetic_algorithm.parameters.")
        sys.exit(1)

    specs = []
    for pcfg in param_list:
        pname = pcfg.get("name")
        if not pname:
            print("Each parameter entry needs a 'name'.")
            sys.exit(1)
        err = validate_param(pname, model_key)
        if err:
            print(f"Parameter error: {err}")
            sys.exit(1)
        specs.append(get_param_spec(pname, pcfg))

    # --- GA settings ---
    s = ga_cfg.get("settings", {}) or {}
    ga_kwargs = dict(
        pop_size   = int(s.get("pop_size", 24)),
        n_gen      = int(s.get("n_gen", 30)),
        cx_pb      = float(s.get("cx_pb", 0.6)),
        mut_pb     = float(s.get("mut_pb", 0.2)),
        sigma_frac = float(s.get("sigma_frac", 0.15)),
        tourn_k    = int(s.get("tourn_k", 3)),
        elitism    = int(s.get("elitism", 2)),
        patience   = int(s.get("patience", 8)),
        seed       = int(s.get("seed", 12345)),
    )

    # --- Targets and weights ---
    raw_targets = cfg.get("targets", {}) or {}
    targets = {k: float(v) for k, v in raw_targets.items()
               if v is not None and k in TARGET_KEYS}
    if not targets:
        print("No targets specified. The GA needs at least one observed target.")
        sys.exit(1)

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
    tag     = "_".join(names)
    out_dir = OUT_BASE / site_id / f"ga_{tag}"
    out_dir.mkdir(parents=True, exist_ok=True)

    work = out_dir / f"_work_{site_id}.sipx"
    shutil.copy2(str(TEMPLATE), str(work))

    print(f"\nSite:       {site_id}")
    if cfg.get("description"):
        print(f"Info:       {cfg['description']}")
    print(f"Model:      {model_info['label']}")
    print(f"Parameters: {', '.join(names)}")
    print(f"GA budget:  pop={ga_kwargs['pop_size']}  gen<={ga_kwargs['n_gen']}  "
          f"(<= {ga_kwargs['pop_size'] * ga_kwargs['n_gen']} SIDRA runs, "
          f"fewer with caching)")
    print(f"Targets:    {targets}")
    print()

    result = None
    setters = {sp["name"]: PARAM_REGISTRY[sp["name"]]["setter"] for sp in specs}

    try:
        with SIDRASession() as sid:
            sid.open_project(str(work))
            site = _get_us_roundabout_site(sid)
            site.ModelSetting.Rou_Capacity_Model = mcode
            _set_geometry(sid, site, icd_m, circ_lanes)
            _set_volumes(sid, site, lv, hv)

            def model_fn(params: dict) -> dict:
                for name, value in params.items():
                    setters[name](sid, site, mcode, value)
                sid.process_site(site)
                raw = sid.read_lane_outputs(site)
                return _read_site_outputs(raw)

            result = genetic_search(
                site_id  = site_id,
                model_fn = model_fn,
                specs    = specs,
                targets  = targets,
                weights  = weights,
                **ga_kwargs,
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

    results_path = out_dir / "ga_results.json"
    results_path.write_text(
        json.dumps(dataclasses.asdict(result), indent=2), encoding="utf-8")
    print(f"Results saved: {results_path}")

    save_plot(cfg, result, out_dir)


if __name__ == "__main__":
    main()
