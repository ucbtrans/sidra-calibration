"""
grid_search.py  -  2D grid search over two user-selected calibration parameters.

Sweeps parameter_1 x parameter_2 over all combinations, evaluates the
multi-target weighted error at each grid point, and returns the combination
that minimizes total error.

Run count: len(p1_values) * len(p2_values).
Practical limit before wall time becomes prohibitive: ~15 x 15 = 225 runs.
Beyond ~3 parameters, use the GA (Phase 3) instead of nested grid search.

No SIDRA dependency - the caller provides model_fn.
"""

from dataclasses import dataclass, field
from typing import Callable
from multi_target import weighted_error, TARGET_KEYS


@dataclass
class GridSearchResult:
    site_id:     str
    param1_name: str
    param2_name: str
    best_p1:     float
    best_p2:     float
    best_error:  float
    grid:        list  = field(default_factory=list)
    # grid rows: {param1_name: v1, param2_name: v2,
    #             capacity_veh_h, q95_veh, delay_s, error}
    p1_values:   list  = field(default_factory=list)
    p2_values:   list  = field(default_factory=list)
    targets:     dict  = field(default_factory=dict)
    weights:     dict  = field(default_factory=dict)
    residuals:   dict  = field(default_factory=dict)
    n_runs:      int   = 0
    notes:       str   = ""


def grid_search_2d(
    site_id:   str,
    model_fn:  Callable[[float, float], dict],
    p1_values: list,
    p2_values: list,
    p1_name:   str,
    p2_name:   str,
    targets:   dict,
    weights:   dict,
) -> GridSearchResult:
    """
    2D grid search: sweep p1_values x p2_values, minimize weighted error.

    Parameters
    ----------
    model_fn  : f(p1, p2) -> dict{capacity_veh_h, q95_veh, delay_s}
                Applied in order: parameter_1 first, then parameter_2.
                Called once per grid point.
    p1_values : ordered list of values for parameter 1
    p2_values : ordered list of values for parameter 2
    p1_name   : parameter name for labels and output keys
    p2_name   : parameter name for labels and output keys
    targets   : observed field values (any subset of TARGET_KEYS)
    weights   : importance weight per target key

    Returns
    -------
    GridSearchResult with .grid (full surface), .best_p1, .best_p2, .residuals
    """
    active_targets = {k: float(v) for k, v in targets.items()
                      if v is not None and float(v) > 0}

    result = GridSearchResult(
        site_id=site_id,
        param1_name=p1_name, param2_name=p2_name,
        best_p1=float("nan"), best_p2=float("nan"),
        best_error=float("inf"),
        p1_values=list(p1_values),
        p2_values=list(p2_values),
        targets=active_targets,
        weights=weights,
    )

    if not active_targets:
        result.notes = "No valid targets - running grid sweep only."

    n_total      = len(p1_values) * len(p2_values)
    n_done       = 0
    best_error   = float("inf")
    best_modeled = {}

    for p1 in p1_values:
        for p2 in p2_values:
            n_done += 1
            try:
                modeled = model_fn(p1, p2)
                err = weighted_error(modeled, active_targets, weights) \
                      if active_targets else None

                row = {p1_name: p1, p2_name: p2, "error": err}
                for k in TARGET_KEYS:
                    v = modeled.get(k)
                    row[k] = round(float(v), 3) if v is not None else None
                result.grid.append(row)

                if err is not None and err < best_error:
                    best_error       = err
                    result.best_p1   = p1
                    result.best_p2   = p2
                    result.best_error = err
                    best_modeled     = {k: modeled.get(k) for k in TARGET_KEYS}

                if n_done % max(1, n_total // 10) == 0 or n_done == n_total:
                    print(f"  Grid progress: {n_done}/{n_total} runs  "
                          f"best error = {best_error:.5f}", flush=True)

            except Exception as exc:
                result.grid.append({
                    p1_name: p1, p2_name: p2,
                    "error": None, "exception": str(exc),
                })
                result.notes += (
                    f"Warning at ({p1_name}={p1}, {p2_name}={p2}): {exc}\n"
                )

    result.n_runs = n_done

    for key, t_val in active_targets.items():
        m_val = best_modeled.get(key)
        if m_val is not None and t_val:
            result.residuals[key] = round((m_val - t_val) / t_val * 100, 2)

    return result
