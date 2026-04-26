"""
calibration.py
Auto-calibration engine for SIDRA roundabout models.

Two methods are implemented:

1. Bisection (default)
   Fast, reliable 1-D root-finding.  Used when calibrating a single
   parameter (Environment Factor or HCM6 Calibration Factor) to match
   observed entry capacity.  Converges in ~10–15 iterations.

2. Genetic Algorithm (optional)
   Used for multi-parameter calibration (e.g., per-leg Environment Factors,
   or simultaneous calibration of fe + Entry-Circulating adjustment level).
   Requires the DEAP library:  pip install deap

When no observed capacity is available (our situation), the engine runs a
sensitivity sweep over the parameter range and returns a results table.
This allows comparison of model outputs across sites and parameter values,
forming the basis of the Task 4 analysis.
"""

import math
import warnings
from dataclasses import dataclass, field
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
FE_MIN     = 0.50   # lower bound for Environment Factor
FE_MAX     = 2.00   # upper bound for Environment Factor
FE_DEFAULT = 1.05   # SIDRA Standard HCM US default (single-lane)

CF_MIN     = 0.50   # lower bound for HCM6 Calibration Factor
CF_MAX     = 2.00
CF_DEFAULT = 1.00

BISECT_TOL   = 0.005   # convergence tolerance on parameter value
BISECT_MAX_ITER = 50


# ---------------------------------------------------------------------------
# Result data structures
# ---------------------------------------------------------------------------
@dataclass
class CalibrationResult:
    site_id:   str
    method:    str          # "bisection" | "ga" | "sensitivity"
    parameter: str          # "fe" | "cf"
    value:     float        # calibrated parameter value
    capacity_estimated: float   # SIDRA capacity at calibrated value (veh/h)
    capacity_observed:  Optional[float] = None
    error_pct:          Optional[float] = None   # (est - obs)/obs * 100
    n_iterations:       int = 0
    converged:          bool = True
    leg_idx:            Optional[int] = None     # None = intersection average
    notes:              str = ""


@dataclass
class SensitivityResult:
    site_id:   str
    parameter: str
    sweep:     list[dict] = field(default_factory=list)
    # Each dict: {value, capacity_avg, capacity_min, capacity_max,
    #             deg_satn_avg, avg_delay_avg}


# ---------------------------------------------------------------------------
# Model function type alias
# A "model function" takes a parameter value and returns average entry capacity
# ---------------------------------------------------------------------------
ModelFn = Callable[[float], float]


# ---------------------------------------------------------------------------
# Bisection calibration
# ---------------------------------------------------------------------------
def calibrate_bisection(
    site_id:            str,
    model_fn:           ModelFn,
    observed_capacity:  float,
    param:              str = "fe",
    p_min:              float = FE_MIN,
    p_max:              float = FE_MAX,
    tol:                float = BISECT_TOL,
    max_iter:           int   = BISECT_MAX_ITER,
) -> CalibrationResult:
    """
    Find the parameter value such that model_fn(p) ≈ observed_capacity.

    For Environment Factor (fe):
      Capacity DECREASES as fe INCREASES → monotone decreasing function.
    For HCM Calibration Factor (cf):
      Capacity DECREASES as cf INCREASES → same direction.

    The bisection is on the error: f(p) = model_fn(p) - observed_capacity.
    We find the root.
    """
    result = CalibrationResult(
        site_id=site_id, method="bisection",
        parameter=param, value=float("nan"),
        capacity_estimated=float("nan"),
        capacity_observed=observed_capacity,
    )

    # Verify monotonicity direction
    cap_lo = model_fn(p_min)
    cap_hi = model_fn(p_max)

    if cap_lo < cap_hi:
        # Unexpected: capacity increases with parameter → swap bounds
        p_min, p_max = p_max, p_min
        cap_lo, cap_hi = cap_hi, cap_lo
        result.notes += "Bounds swapped (unexpected monotonicity). "

    if observed_capacity > cap_lo:
        result.converged = False
        result.notes += (f"Observed capacity {observed_capacity:.0f} > max model "
                         f"capacity {cap_lo:.0f} at {param}={p_min:.2f}. "
                         "Using minimum parameter value.")
        result.value = p_min
        result.capacity_estimated = cap_lo
        result.error_pct = (cap_lo - observed_capacity) / observed_capacity * 100
        return result

    if observed_capacity < cap_hi:
        result.converged = False
        result.notes += (f"Observed capacity {observed_capacity:.0f} < min model "
                         f"capacity {cap_hi:.0f} at {param}={p_max:.2f}. "
                         "Using maximum parameter value.")
        result.value = p_max
        result.capacity_estimated = cap_hi
        result.error_pct = (cap_hi - observed_capacity) / observed_capacity * 100
        return result

    # Bisection loop
    lo, hi = p_min, p_max
    for i in range(max_iter):
        mid = (lo + hi) / 2.0
        cap_mid = model_fn(mid)
        error = cap_mid - observed_capacity

        if abs(hi - lo) < tol:
            result.value = mid
            result.capacity_estimated = cap_mid
            result.error_pct = error / observed_capacity * 100
            result.n_iterations = i + 1
            result.converged = True
            return result

        # Capacity decreases with parameter, so:
        if error > 0:   # cap_mid > observed → need to increase param
            lo = mid
        else:           # cap_mid < observed → need to decrease param
            hi = mid

    # Max iterations reached
    result.value = (lo + hi) / 2.0
    result.capacity_estimated = model_fn(result.value)
    result.error_pct = (result.capacity_estimated - observed_capacity) / observed_capacity * 100
    result.n_iterations = max_iter
    result.converged = abs(hi - lo) < tol * 10
    return result


# ---------------------------------------------------------------------------
# Sensitivity sweep (no observed data required)
# ---------------------------------------------------------------------------
def sensitivity_sweep(
    site_id:  str,
    model_fn: Callable[[float], dict],
    param:    str = "fe",
    p_min:    float = FE_MIN,
    p_max:    float = FE_MAX,
    n_steps:  int = 16,
) -> SensitivityResult:
    """
    Sweep parameter from p_min to p_max in n_steps and record outputs.

    model_fn must accept a parameter value and return a dict with keys:
      capacities  : list of per-lane capacities (veh/h)
      deg_satns   : list of per-lane degrees of saturation
      avg_delays  : list of per-leg average delays (s/veh) or None

    Returns a SensitivityResult with the sweep table.

    This is the primary analysis mode when no field data is available.
    """
    result = SensitivityResult(site_id=site_id, parameter=param)
    step = (p_max - p_min) / (n_steps - 1)

    for i in range(n_steps):
        p = p_min + i * step
        try:
            out = model_fn(p)
            caps    = out.get("capacities", [])
            dsatns  = out.get("deg_satns", [])
            delays  = [d for d in out.get("avg_delays", []) if d is not None]

            result.sweep.append({
                "value":          round(p, 4),
                "capacity_avg":   _mean(caps),
                "capacity_min":   min(caps) if caps else None,
                "capacity_max":   max(caps) if caps else None,
                "deg_satn_avg":   _mean(dsatns),
                "avg_delay_avg":  _mean(delays) if delays else None,
            })
        except Exception as e:
            result.sweep.append({
                "value": round(p, 4),
                "error": str(e),
            })

    return result


# ---------------------------------------------------------------------------
# Genetic Algorithm calibration (multi-parameter)
# ---------------------------------------------------------------------------
def calibrate_ga(
    site_id:           str,
    model_fn:          Callable[[list[float]], float],
    observed_capacity: float,
    param_bounds:      list[tuple[float, float]],
    n_generations:     int = 50,
    pop_size:          int = 30,
    crossover_prob:    float = 0.7,
    mutation_prob:     float = 0.2,
    seed:              int = 42,
) -> CalibrationResult:
    """
    Multi-parameter calibration using a Genetic Algorithm.

    Parameters
    ----------
    model_fn       : f(params: list[float]) -> capacity (float)
    observed_capacity : target capacity to match
    param_bounds   : list of (min, max) for each parameter
    n_generations  : GA generations
    pop_size       : population size

    Requires:  pip install deap
    """
    try:
        import random
        from deap import base, creator, tools, algorithms
    except ImportError:
        raise ImportError(
            "DEAP library required for GA calibration.\n"
            "Install with:  pip install deap\n"
            "Or use calibrate_bisection() for single-parameter calibration."
        )

    random.seed(seed)
    n_params = len(param_bounds)

    # Fitness: minimize absolute error between model capacity and observed
    if not hasattr(creator, "FitnessMin"):
        creator.create("FitnessMin", base.Fitness, weights=(-1.0,))
    if not hasattr(creator, "Individual"):
        creator.create("Individual", list, fitness=creator.FitnessMin)

    toolbox = base.Toolbox()

    # Gene: uniform random in each parameter's range
    def make_individual():
        return creator.Individual(
            [random.uniform(lo, hi) for lo, hi in param_bounds]
        )

    def evaluate(individual):
        params = [
            max(lo, min(hi, individual[i]))
            for i, (lo, hi) in enumerate(param_bounds)
        ]
        cap = model_fn(params)
        return (abs(cap - observed_capacity),)

    toolbox.register("individual", make_individual)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("evaluate",   evaluate)
    toolbox.register("mate",       tools.cxBlend, alpha=0.5)
    toolbox.register("mutate",     tools.mutGaussian,
                     mu=0, sigma=0.1, indpb=0.3)
    toolbox.register("select",     tools.selTournament, tournsize=3)

    pop = toolbox.population(n=pop_size)
    hof = tools.HallOfFame(1)

    algorithms.eaSimple(
        pop, toolbox,
        cxpb=crossover_prob, mutpb=mutation_prob,
        ngen=n_generations, halloffame=hof,
        verbose=False,
    )

    best = hof[0]
    best_params = [max(lo, min(hi, best[i]))
                   for i, (lo, hi) in enumerate(param_bounds)]
    cap_est = model_fn(best_params)

    return CalibrationResult(
        site_id=site_id, method="ga",
        parameter=",".join([f"p{i}" for i in range(n_params)]),
        value=best_params[0] if n_params == 1 else float("nan"),
        capacity_estimated=cap_est,
        capacity_observed=observed_capacity,
        error_pct=(cap_est - observed_capacity) / observed_capacity * 100,
        n_iterations=n_generations * pop_size,
        converged=True,
        notes=f"Best params: {[round(p, 4) for p in best_params]}",
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
def _mean(values: list) -> Optional[float]:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    return sum(vals) / len(vals) if vals else None
