"""
Tests for calibration.py — bisection, sensitivity sweep, GA.
No SIDRA required — model functions are simple Python callables.
"""

import math
import os
import sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from calibration import (
    calibrate_bisection, sensitivity_sweep,
    CalibrationResult, SensitivityResult,
    FE_MIN, FE_MAX, FE_DEFAULT, BISECT_TOL,
)


# ---------------------------------------------------------------------------
# Model stubs
# ---------------------------------------------------------------------------
def linear_capacity(fe: float) -> float:
    """Capacity decreases linearly from 2000 (fe=0.5) to 500 (fe=2.0)."""
    return 2000 - 1000 * (fe - 0.5)


def sweep_model(fe: float) -> dict:
    cap = linear_capacity(fe)
    return {
        "capacities": [cap, cap * 0.95],
        "deg_satns":  [0.3, 0.35],
        "avg_delays": [8.0, 9.0],
    }


def error_model(fe: float) -> dict:
    if fe > 1.5:
        raise RuntimeError("Simulated SIDRA error")
    return sweep_model(fe)


# ---------------------------------------------------------------------------
# Bisection calibration
# ---------------------------------------------------------------------------
class TestCalibrateBisection:
    def test_finds_correct_fe(self):
        target = 1200.0
        result = calibrate_bisection("SITE-1", linear_capacity, target)
        assert result.converged
        assert abs(result.capacity_estimated - target) / target < 0.01
        assert FE_MIN <= result.value <= FE_MAX

    def test_converges_within_tolerance(self):
        result = calibrate_bisection("SITE-1", linear_capacity, 1500.0,
                                     tol=BISECT_TOL)
        assert result.converged
        assert abs(result.value - result.value) < BISECT_TOL * 10

    def test_result_structure(self):
        result = calibrate_bisection("TEST", linear_capacity, 1000.0)
        assert isinstance(result, CalibrationResult)
        assert result.site_id == "TEST"
        assert result.method == "bisection"
        assert result.parameter == "fe"
        assert result.capacity_observed == 1000.0
        assert result.n_iterations > 0

    def test_above_max_capacity(self):
        # Target higher than model can produce at fe_min
        cap_at_min = linear_capacity(FE_MIN)
        result = calibrate_bisection("SITE-2", linear_capacity,
                                     cap_at_min + 500)
        assert not result.converged
        assert "Using minimum" in result.notes

    def test_below_min_capacity(self):
        cap_at_max = linear_capacity(FE_MAX)
        result = calibrate_bisection("SITE-3", linear_capacity,
                                     cap_at_max - 200)
        assert not result.converged
        assert "Using maximum" in result.notes

    def test_error_pct_calculated(self):
        result = calibrate_bisection("SITE-4", linear_capacity, 1200.0)
        assert result.error_pct is not None
        assert abs(result.error_pct) < 2.0  # within 2%

    def test_cf_parameter_label(self):
        result = calibrate_bisection("SITE-5", linear_capacity, 1200.0,
                                     param="cf")
        assert result.parameter == "cf"

    def test_custom_bounds(self):
        result = calibrate_bisection("SITE-6", linear_capacity, 1400.0,
                                     p_min=0.9, p_max=1.3)
        assert 0.9 <= result.value <= 1.3

    def test_monotone_check(self):
        # A function that INCREASES with parameter (unexpected) — should swap
        def increasing(fe): return 500 + 1000 * (fe - 0.5)
        result = calibrate_bisection("SITE-7", increasing, 1000.0)
        # Should still find a result (bounds swapped)
        assert result.capacity_estimated is not None


# ---------------------------------------------------------------------------
# Sensitivity sweep
# ---------------------------------------------------------------------------
class TestSensitivitySweep:
    def test_returns_correct_step_count(self):
        result = sensitivity_sweep("SITE-1", sweep_model, n_steps=8)
        assert isinstance(result, SensitivityResult)
        assert len(result.sweep) == 8

    def test_default_16_steps(self):
        result = sensitivity_sweep("SITE-1", sweep_model)
        assert len(result.sweep) == 16

    def test_parameter_range(self):
        result = sensitivity_sweep("SITE-1", sweep_model, n_steps=10)
        values = [pt["value"] for pt in result.sweep]
        assert min(values) == pytest.approx(FE_MIN, abs=0.01)
        assert max(values) == pytest.approx(FE_MAX, abs=0.01)

    def test_capacity_decreases_with_fe(self):
        result = sensitivity_sweep("SITE-1", sweep_model, n_steps=10)
        caps = [pt["capacity_avg"] for pt in result.sweep if "error" not in pt]
        # Should be monotonically decreasing
        for i in range(len(caps) - 1):
            assert caps[i] >= caps[i+1]

    def test_delay_recorded(self):
        result = sensitivity_sweep("SITE-1", sweep_model, n_steps=4)
        delays = [pt.get("avg_delay_avg") for pt in result.sweep]
        assert all(d is not None for d in delays)

    def test_error_in_sweep_recorded(self):
        result = sensitivity_sweep("SITE-1", error_model, n_steps=16)
        # Some points will have errors (fe > 1.5)
        error_points = [pt for pt in result.sweep if "error" in pt]
        assert len(error_points) > 0

    def test_successful_points_have_stats(self):
        result = sensitivity_sweep("SITE-1", sweep_model, n_steps=4)
        for pt in result.sweep:
            if "error" not in pt:
                assert "capacity_avg" in pt
                assert "capacity_min" in pt
                assert "capacity_max" in pt
                assert "deg_satn_avg" in pt
                assert pt["capacity_min"] <= pt["capacity_avg"] <= pt["capacity_max"]

    def test_site_id_stored(self):
        result = sensitivity_sweep("MY-SITE-99", sweep_model)
        assert result.site_id == "MY-SITE-99"

    def test_none_delays_excluded(self):
        def model_with_none_delays(fe):
            return {"capacities": [1000.0], "deg_satns": [0.3], "avg_delays": [None]}
        result = sensitivity_sweep("SITE-1", model_with_none_delays, n_steps=4)
        for pt in result.sweep:
            assert pt.get("avg_delay_avg") is None
