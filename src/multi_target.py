"""
multi_target.py  -  Multi-target calibration engine.

Sweeps one input parameter and finds the value that minimizes
weighted normalized error across multiple observed output targets.

Supported targets:
  capacity_veh_h  - entry capacity C (veh/h per entry lane)
  q95_veh         - 95th percentile queue Q95 (vehicles)
  delay_s         - average control delay d (s/veh)

tc/tf (critical gap, follow-up headway) are reserved for a future
extension requiring direct video gap-acceptance measurement.

No SIDRA dependency - pure Python. The caller provides model_fn.
"""

import math
from dataclasses import dataclass, field
from typing import Callable, Optional


TARGET_KEYS = ("capacity_veh_h", "q95_veh", "delay_s")

TARGET_LABELS = {
    "capacity_veh_h": "Entry Capacity C (veh/h)",
    "q95_veh":        "95th Pct Queue Q95 (veh)",
    "delay_s":        "Average Delay d (s/veh)",
}

DEFAULT_WEIGHTS = {
    "capacity_veh_h": 1.0,
    "q95_veh":        0.5,
    "delay_s":        0.3,
}

# Valid parameter ranges
PARAM_RANGES = {
    "fe": (0.5, 2.0),
    "cf": (0.7, 1.3),
}


@dataclass
class MultiTargetResult:
    site_id:    str
    parameter:  str
    best_value: float
    best_error: float
    sweep:      list  = field(default_factory=list)
    # Each sweep row: {param_value, capacity_veh_h, q95_veh, delay_s, error}
    targets:    dict  = field(default_factory=dict)
    weights:    dict  = field(default_factory=dict)
    residuals:  dict  = field(default_factory=dict)
    # residuals: {key: (modeled - target) / target * 100} at best_value
    converged:  bool  = True
    notes:      str   = ""


def weighted_error(modeled: dict, targets: dict, weights: dict) -> float:
    """
    Normalized weighted squared error across all active targets.

    error = (1 / sum_w) * sum_i( w_i * ((y_i - t_i) / t_i)^2 )

    Returns inf if no target can be evaluated.
    """
    total = 0.0
    w_sum = 0.0
    for key, t_val in targets.items():
        if t_val is None or t_val <= 0:
            continue
        m_val = modeled.get(key)
        if m_val is None or m_val <= 0:
            continue
        w = weights.get(key, 1.0)
        total += w * ((m_val - t_val) / t_val) ** 2
        w_sum += w
    return (total / w_sum) if w_sum > 0 else float("inf")


def calibrate_multi_target(
    site_id:  str,
    model_fn: Callable[[float], dict],
    targets:  dict,
    weights:  dict   = None,
    param:    str    = "fe",
    p_min:    float  = None,
    p_max:    float  = None,
    n_steps:  int    = 30,
) -> MultiTargetResult:
    """
    Find the input parameter value that minimizes weighted error across targets.

    Parameters
    ----------
    site_id   : identifier for reporting
    model_fn  : f(param_value: float) -> dict{capacity_veh_h, q95_veh, delay_s}
                Called once per sweep step. Must run SIDRA and return outputs.
    targets   : observed field values; use any subset of TARGET_KEYS.
                Set to {} for a pure sensitivity sweep with no target matching.
    weights   : importance weight per target key.
                Defaults: capacity=1.0, q95=0.5, delay=0.3
    param     : parameter name ("fe" or "cf") - used for labels only
    p_min/max : sweep range (defaults from PARAM_RANGES if not specified)
    n_steps   : number of evenly-spaced steps across [p_min, p_max]

    Returns
    -------
    MultiTargetResult with:
      .sweep       - full sweep table (list of dicts)
      .best_value  - parameter value at minimum weighted error
      .best_error  - minimum weighted error achieved
      .residuals   - per-target % error at best_value
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS.copy()

    if p_min is None:
        p_min = PARAM_RANGES.get(param, (0.5, 2.0))[0]
    if p_max is None:
        p_max = PARAM_RANGES.get(param, (0.5, 2.0))[1]

    active_targets = {k: float(v) for k, v in targets.items()
                      if v is not None and float(v) > 0}

    result = MultiTargetResult(
        site_id=site_id,
        parameter=param,
        best_value=float("nan"),
        best_error=float("inf"),
        targets=active_targets,
        weights=weights,
    )

    if not active_targets:
        result.notes = "No valid targets - running sensitivity sweep only."

    step = (p_max - p_min) / max(n_steps - 1, 1)
    best_value   = p_min
    best_error   = float("inf")
    best_modeled = {}

    for i in range(n_steps):
        p = round(p_min + i * step, 6)
        try:
            modeled = model_fn(p)
            err = weighted_error(modeled, active_targets, weights) \
                  if active_targets else None

            row = {"param_value": p, "error": err}
            for k in TARGET_KEYS:
                v = modeled.get(k)
                row[k] = round(float(v), 3) if v is not None else None
            result.sweep.append(row)

            if err is not None and err < best_error:
                best_error   = err
                best_value   = p
                best_modeled = {k: modeled.get(k) for k in TARGET_KEYS}

        except Exception as exc:
            result.sweep.append({"param_value": p, "error": None,
                                  "exception": str(exc)})
            result.notes += f"Warning at {param}={p:.4f}: {exc}\n"

    result.best_value = best_value
    result.best_error = best_error

    for key, t_val in active_targets.items():
        m_val = best_modeled.get(key)
        if m_val and t_val:
            result.residuals[key] = round((m_val - t_val) / t_val * 100, 2)

    return result
