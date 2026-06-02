"""
genetic_search.py  -  Genetic algorithm for N-parameter SIDRA calibration.

Phase 3 of the Task 5 calibration tool. Optimizes three or more calibration
parameters simultaneously by minimizing the multi-target weighted error.

Self-contained: uses only the Python standard library (random) plus the
weighted_error function from multi_target. No SIDRA dependency - the caller
supplies model_fn. No third-party GA library, so there is no compiler or
install risk for the engineers who run the tool.

Why a GA here: beyond two parameters a full grid search is exponential
(15^3 = 3375 SIDRA runs). The GA explores the parameter space with a fixed
evaluation budget (population x generations) and converges on a good
combination without enumerating the whole grid.

Mixed variables:
  continuous   gene is a float clamped to [lo, hi]
  categorical  gene is a float decoded to the nearest value index

Evaluation cache: every fitness evaluation is one SIDRA run, and the GA
revisits points often. Results are memoized by decoded parameter values so
each distinct combination is run at most once.
"""

import random
from dataclasses import dataclass, field
from typing import Callable

from multi_target import weighted_error, TARGET_KEYS


# ---------------------------------------------------------------------------
# Parameter spec
# ---------------------------------------------------------------------------
# Each parameter to calibrate is described by a spec dict:
#   {"name": str, "type": "continuous", "lo": float, "hi": float}
#   {"name": str, "type": "categorical", "values": [...]}
#
# build_specs() in calibrate_ga.py constructs these from PARAM_REGISTRY.


@dataclass
class GAResult:
    site_id:      str
    param_names:  list
    best_params:  dict   = field(default_factory=dict)
    best_error:   float  = float("inf")
    best_outputs: dict   = field(default_factory=dict)
    residuals:    dict   = field(default_factory=dict)
    history:      list    = field(default_factory=list)
    # history rows: {gen, best_error, mean_error, n_evals_total}
    n_evals:      int    = 0          # distinct SIDRA runs (cache misses)
    n_requests:   int    = 0          # total fitness lookups (incl. cache hits)
    targets:      dict   = field(default_factory=dict)
    weights:      dict   = field(default_factory=dict)
    settings:     dict   = field(default_factory=dict)
    converged:    bool   = False
    notes:        str    = ""


# ---------------------------------------------------------------------------
# Gene encode / decode
# ---------------------------------------------------------------------------
def _gene_bounds(spec: dict):
    """Return (lo, hi) of the raw gene space for a parameter spec."""
    if spec["type"] == "categorical":
        return 0.0, float(len(spec["values"]) - 1)
    return float(spec["lo"]), float(spec["hi"])


def _decode_gene(spec: dict, gene: float):
    """Map a raw gene value to the actual parameter value."""
    if spec["type"] == "categorical":
        n = len(spec["values"])
        idx = int(round(gene))
        idx = max(0, min(n - 1, idx))
        return spec["values"][idx]
    lo, hi = float(spec["lo"]), float(spec["hi"])
    return max(lo, min(hi, float(gene)))


def _decode(specs: list, individual: list) -> dict:
    """Decode a full individual into {param_name: actual_value}."""
    return {spec["name"]: _decode_gene(spec, g)
            for spec, g in zip(specs, individual)}


def _cache_key(specs: list, params: dict):
    """Stable key for the evaluation cache (rounds continuous values)."""
    key = []
    for spec in specs:
        v = params[spec["name"]]
        if spec["type"] == "categorical":
            key.append(("c", v))
        else:
            key.append(("f", round(float(v), 4)))
    return tuple(key)


# ---------------------------------------------------------------------------
# Genetic operators
# ---------------------------------------------------------------------------
def _clamp_individual(specs, individual):
    out = []
    for spec, g in zip(specs, individual):
        lo, hi = _gene_bounds(spec)
        out.append(max(lo, min(hi, g)))
    return out


def _random_individual(specs, rng):
    ind = []
    for spec in specs:
        lo, hi = _gene_bounds(spec)
        ind.append(rng.uniform(lo, hi))
    return ind


def _tournament_select(pop, fits, k, rng):
    """Return a copy of the best of k randomly chosen individuals."""
    best_i = None
    for _ in range(k):
        i = rng.randrange(len(pop))
        if best_i is None or fits[i] < fits[best_i]:
            best_i = i
    return list(pop[best_i])


def _blend_crossover(a, b, alpha, rng):
    """BLX-alpha crossover: child genes drawn from an expanded interval."""
    c1, c2 = [], []
    for ga, gb in zip(a, b):
        lo, hi = min(ga, gb), max(ga, gb)
        span = hi - lo
        ext_lo = lo - alpha * span
        ext_hi = hi + alpha * span
        c1.append(rng.uniform(ext_lo, ext_hi))
        c2.append(rng.uniform(ext_lo, ext_hi))
    return c1, c2


def _mutate(specs, individual, mut_pb, sigma_frac, rng):
    """Gaussian per-gene mutation, sigma scaled to each gene's range."""
    out = []
    for spec, g in zip(specs, individual):
        if rng.random() < mut_pb:
            lo, hi = _gene_bounds(spec)
            sigma = sigma_frac * (hi - lo)
            g = g + rng.gauss(0.0, sigma if sigma > 0 else 1.0)
        out.append(g)
    return out


# ---------------------------------------------------------------------------
# Main GA
# ---------------------------------------------------------------------------
def genetic_search(
    site_id:     str,
    model_fn:    Callable[[dict], dict],
    specs:       list,
    targets:     dict,
    weights:     dict,
    pop_size:    int   = 24,
    n_gen:       int   = 30,
    cx_pb:       float = 0.6,
    mut_pb:      float = 0.2,
    sigma_frac:  float = 0.15,
    tourn_k:     int   = 3,
    elitism:     int   = 2,
    patience:    int   = 8,
    seed:        int   = 12345,
) -> GAResult:
    """
    Minimize multi-target weighted error over N parameters with a GA.

    Parameters
    ----------
    model_fn   : f(params: dict{name: value}) -> dict{capacity_veh_h, q95_veh, delay_s}
                 Runs SIDRA once. Called once per distinct parameter combination
                 (repeated combinations are served from the cache).
    specs      : list of parameter spec dicts (see module header)
    targets    : observed field values (subset of TARGET_KEYS)
    weights    : importance weight per target key
    pop_size   : individuals per generation
    n_gen      : maximum generations
    cx_pb      : crossover probability per pair
    mut_pb     : mutation probability per gene
    sigma_frac : Gaussian mutation sigma as a fraction of each gene's range
    tourn_k    : tournament size for selection
    elitism    : number of best individuals carried over unchanged
    patience   : stop if best error does not improve for this many generations
    seed       : RNG seed for reproducibility

    Returns
    -------
    GAResult with best_params, best_error, residuals, and convergence history.
    """
    rng = random.Random(seed)

    active_targets = {k: float(v) for k, v in targets.items()
                      if v is not None and float(v) > 0}

    param_names = [s["name"] for s in specs]
    result = GAResult(
        site_id=site_id,
        param_names=param_names,
        targets=active_targets,
        weights=weights,
        settings={
            "pop_size": pop_size, "n_gen": n_gen, "cx_pb": cx_pb,
            "mut_pb": mut_pb, "sigma_frac": sigma_frac, "tourn_k": tourn_k,
            "elitism": elitism, "patience": patience, "seed": seed,
        },
    )

    if not active_targets:
        result.notes = "No valid targets - GA requires at least one target.\n"
        return result

    cache = {}

    def evaluate(individual):
        """Decode, run (or fetch cached) model, return (error, params, outputs)."""
        params = _decode(specs, individual)
        key = _cache_key(specs, params)
        result.n_requests += 1
        if key in cache:
            return cache[key]
        try:
            outputs = model_fn(params)
            err = weighted_error(outputs, active_targets, weights)
        except Exception as exc:
            outputs, err = {}, float("inf")
            result.notes += f"Eval error at {params}: {exc}\n"
        result.n_evals += 1
        cache[key] = (err, params, outputs)
        return cache[key]

    # --- Initial population ---
    pop = [_random_individual(specs, rng) for _ in range(pop_size)]
    evals = [evaluate(ind) for ind in pop]
    fits = [e[0] for e in evals]

    best_i = min(range(pop_size), key=lambda i: fits[i])
    best_err, best_params, best_outputs = evals[best_i]
    best_ind = list(pop[best_i])

    stale = 0
    for gen in range(1, n_gen + 1):
        # Elitism: carry over the best individuals
        order = sorted(range(pop_size), key=lambda i: fits[i])
        elites = [list(pop[i]) for i in order[:elitism]]

        # Build offspring via selection, crossover, mutation
        offspring = []
        while len(offspring) < pop_size - elitism:
            p1 = _tournament_select(pop, fits, tourn_k, rng)
            p2 = _tournament_select(pop, fits, tourn_k, rng)
            if rng.random() < cx_pb:
                c1, c2 = _blend_crossover(p1, p2, alpha=0.3, rng=rng)
            else:
                c1, c2 = p1, p2
            c1 = _clamp_individual(specs, _mutate(specs, c1, mut_pb, sigma_frac, rng))
            c2 = _clamp_individual(specs, _mutate(specs, c2, mut_pb, sigma_frac, rng))
            offspring.append(c1)
            if len(offspring) < pop_size - elitism:
                offspring.append(c2)

        pop = elites + offspring
        evals = [evaluate(ind) for ind in pop]
        fits = [e[0] for e in evals]

        gen_best_i = min(range(pop_size), key=lambda i: fits[i])
        gen_best_err = fits[gen_best_i]
        finite = [f for f in fits if f != float("inf")]
        mean_err = sum(finite) / len(finite) if finite else float("inf")

        if gen_best_err < best_err - 1e-9:
            best_err, best_params, best_outputs = evals[gen_best_i]
            best_ind = list(pop[gen_best_i])
            stale = 0
        else:
            stale += 1

        result.history.append({
            "gen": gen,
            "best_error": round(best_err, 6),
            "mean_error": round(mean_err, 6) if mean_err != float("inf") else None,
            "n_evals_total": result.n_evals,
        })

        if stale >= patience:
            result.converged = True
            result.notes += (f"Converged: no improvement for {patience} "
                             f"generations (stopped at gen {gen}).\n")
            break

    result.best_params  = best_params
    result.best_error   = best_err
    result.best_outputs = {k: best_outputs.get(k) for k in TARGET_KEYS}

    for key, t_val in active_targets.items():
        m_val = best_outputs.get(key)
        if m_val and t_val:
            result.residuals[key] = round((m_val - t_val) / t_val * 100, 2)

    return result
