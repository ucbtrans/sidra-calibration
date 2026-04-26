"""
Tests for volumes.py — peak-hour volume estimation.
No external dependencies required.
"""

import os
import sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from volumes import (
    generate_turning_movements, AADTLookup,
    _assign_approach_volumes, _distribute_od,
    K_FACTOR, D_FACTOR, HV_PCT, SYNTHETIC_AADT,
)


# ---------------------------------------------------------------------------
# _assign_approach_volumes
# ---------------------------------------------------------------------------
class TestAssignApproachVolumes:
    def test_three_leg_ramp(self):
        idxs = [0, 2, 4]
        vols = _assign_approach_volumes(idxs, ph_main=500, ph_cross=200,
                                        is_ramp=True, n_legs=3)
        assert vols[0] == 500
        assert vols[2] == 500
        assert vols[4] == 200

    def test_three_leg_crossroad(self):
        idxs = [0, 2, 4]
        vols = _assign_approach_volumes(idxs, ph_main=500, ph_cross=200,
                                        is_ramp=False, n_legs=3)
        assert vols[0] == 500
        assert vols[2] == 200
        assert vols[4] == 200

    def test_four_leg_ramp(self):
        idxs = [0, 2, 4, 6]
        vols = _assign_approach_volumes(idxs, ph_main=500, ph_cross=200,
                                        is_ramp=True, n_legs=4)
        assert vols[0] == 500
        assert vols[4] == 500
        assert vols[2] == 200
        assert vols[6] == 200

    def test_four_leg_crossroad_equal(self):
        idxs = [0, 2, 4, 6]
        vols = _assign_approach_volumes(idxs, ph_main=400, ph_cross=200,
                                        is_ramp=False, n_legs=4)
        # All equal: (400+200)//4 = 150
        assert all(v == 150 for v in vols.values())

    def test_two_leg_fallback(self):
        idxs = [0, 4]
        vols = _assign_approach_volumes(idxs, ph_main=500, ph_cross=200,
                                        is_ramp=True, n_legs=2)
        # Falls into else: total / n = 700 / 2 = 350
        assert all(v == 350 for v in vols.values())

    def test_returns_all_legs(self):
        idxs = [0, 2, 4]
        vols = _assign_approach_volumes(idxs, 300, 100, False, 3)
        assert set(vols.keys()) == {0, 2, 4}


# ---------------------------------------------------------------------------
# _distribute_od
# ---------------------------------------------------------------------------
class TestDistributeOD:
    def test_od_keys_cover_all_pairs(self):
        idxs = [0, 2, 4]
        vols = {0: 300, 2: 300, 4: 300}
        od = _distribute_od(idxs, vols, is_ramp=False, hv_pct=0.06)
        expected_pairs = {(0,2),(0,4),(2,0),(2,4),(4,0),(4,2)}
        assert set(od.keys()) == expected_pairs

    def test_two_destinations_split(self):
        idxs = [0, 2, 4]
        vols = {0: 200, 2: 200, 4: 200}
        od = _distribute_od(idxs, vols, is_ramp=False, hv_pct=0.0)
        # 3-leg: 50/50 split, no HV
        lv_02, hv_02 = od[(0, 2)]
        lv_04, hv_04 = od[(0, 4)]
        assert lv_02 == lv_04
        assert hv_02 == 0
        assert hv_04 == 0

    def test_hv_fraction(self):
        idxs = [0, 4]
        vols = {0: 100, 4: 100}
        od = _distribute_od(idxs, vols, is_ramp=False, hv_pct=0.10)
        lv, hv = od[(0, 4)]
        # total = 100, splits = [1.0], lv = int(100*1.0*0.90)=90, hv=int(100*1.0*0.10)=10
        assert lv == 90
        assert hv == 10

    def test_no_u_turns(self):
        idxs = [0, 2, 4]
        vols = {0: 300, 2: 300, 4: 300}
        od = _distribute_od(idxs, vols, is_ramp=False, hv_pct=0.0)
        assert (0, 0) not in od
        assert (2, 2) not in od
        assert (4, 4) not in od

    def test_volumes_positive(self):
        idxs = [0, 2, 4]
        vols = {0: 10, 2: 10, 4: 10}
        od = _distribute_od(idxs, vols, is_ramp=False, hv_pct=0.06)
        for lv, hv in od.values():
            assert lv >= 1
            assert hv >= 0


# ---------------------------------------------------------------------------
# generate_turning_movements
# ---------------------------------------------------------------------------
class TestGenerateTurningMovements:
    def test_synthetic_volumes(self):
        tm = generate_turning_movements(
            site_id="TEST-1", n_legs=3, leg_idxs=[0, 2, 4],
            is_ramp=False, route1="199", pm1=0.8,
        )
        assert tm.aadt_source == "synthetic"
        assert len(tm.volumes) == 6  # 3 legs × 2 destinations each
        assert all(v[0] > 0 for v in tm.volumes.values())

    def test_ramp_pattern_dominates_main(self):
        tm_ramp = generate_turning_movements(
            site_id="RAMP-1", n_legs=3, leg_idxs=[0, 2, 4],
            is_ramp=True, route1="101", pm1=88.0, scenario="medium",
        )
        tm_cross = generate_turning_movements(
            site_id="CROSS-1", n_legs=3, leg_idxs=[0, 2, 4],
            is_ramp=False, route1="199", pm1=0.8, scenario="medium",
        )
        # Ramp sites should have higher total volume on main legs
        ramp_total = sum(v[0] + v[1] for v in tm_ramp.volumes.values())
        cross_total = sum(v[0] + v[1] for v in tm_cross.volumes.values())
        assert ramp_total > 0
        assert cross_total > 0

    def test_hv_included(self):
        tm = generate_turning_movements(
            site_id="HV-1", n_legs=3, leg_idxs=[0, 2, 4],
            is_ramp=False, route1="101", pm1=88.0, hv_pct=0.10,
        )
        # Some HV should be present
        total_hv = sum(v[1] for v in tm.volumes.values())
        assert total_hv > 0

    def test_four_leg_site(self):
        tm = generate_turning_movements(
            site_id="4L-1", n_legs=4, leg_idxs=[0, 2, 4, 6],
            is_ramp=False, route1="20", pm1=8.3,
        )
        # 4 legs × 3 destinations each = 12 OD pairs
        assert len(tm.volumes) == 12

    def test_scenario_affects_volume(self):
        tm_low = generate_turning_movements(
            "S1", 3, [0,2,4], False, "1", 1.0, scenario="low")
        tm_high = generate_turning_movements(
            "S2", 3, [0,2,4], False, "1", 1.0, scenario="high")
        total_low  = sum(v[0] for v in tm_low.volumes.values())
        total_high = sum(v[0] for v in tm_high.volumes.values())
        assert total_high > total_low


# ---------------------------------------------------------------------------
# AADTLookup
# ---------------------------------------------------------------------------
class TestAADTLookup:
    def test_missing_file_warns(self):
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            lookup = AADTLookup("/nonexistent/aadt.csv")
            assert len(w) == 1
            assert "not found" in str(w[0].message).lower()
        assert lookup.lookup("101", 88.0) is None

    def test_lookup_returns_none_without_data(self):
        lookup = AADTLookup("/nonexistent/path.csv")
        assert lookup.lookup("101", 88.0, district=1) is None
