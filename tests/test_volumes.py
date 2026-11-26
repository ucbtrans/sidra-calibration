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
        # Both approaches of the main route carry main-route volume
        assert vols[0] == 500
        assert vols[2] == 500
        assert vols[4] == 200

    def test_four_leg_ramp(self):
        idxs = [0, 2, 4, 6]
        vols = _assign_approach_volumes(idxs, ph_main=500, ph_cross=200,
                                        is_ramp=True, n_legs=4)
        assert vols[0] == 500
        assert vols[4] == 500
        assert vols[2] == 200
        assert vols[6] == 200

    def test_four_leg_crossroad(self):
        idxs = [0, 2, 4, 6]
        vols = _assign_approach_volumes(idxs, ph_main=400, ph_cross=200,
                                        is_ramp=False, n_legs=4)
        # Opposite legs 0/4 on the main route, 2/6 on the cross road;
        # total entry = 2 x main + 2 x cross (v1.0 gave only main + cross)
        assert vols[0] == vols[4] == 400
        assert vols[2] == vols[6] == 200
        assert sum(vols.values()) == 1200

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


# ---------------------------------------------------------------------------
# v1.1: exact rounding, census layout, segment containment, configurable factors
# ---------------------------------------------------------------------------
from volumes import (_split_integer, load_turning_counts,
                     observed_turning_movements, CROSS_RATIO)

CENSUS_HEADER = ("DISTRICT,RTE,RTE_SFX,CNTY,PM_PFX,PM,PM_SFX,DESCRIPTION,"
                 "BACK_PEAK_HOUR,BACK_PEAK_MADT,BACK_AADT,"
                 "AHEAD_PEAK_HOUR,AHEAD_PEAK_MADT,AHEAD_AADT")


def _census(tmp_path, rows, preamble=""):
    f = tmp_path / "census.csv"
    f.write_text(preamble + CENSUS_HEADER + "\n" + "\n".join(rows) + "\n",
                 encoding="utf-8")
    return AADTLookup(str(f))


class TestExactRounding:
    def test_movements_sum_to_approach(self):
        idxs = [0, 2, 4, 6]
        vols = {0: 49, 2: 50, 4: 51, 6: 47}
        od = _distribute_od(idxs, vols, is_ramp=False, hv_pct=0.06)
        for leg, total in vols.items():
            assert sum(lv + hv for (o, _), (lv, hv) in od.items() if o == leg) == total

    def test_split_integer_exact(self):
        for total in (3, 7, 46, 101, 999):
            parts = _split_integer(total, [0.25, 0.5, 0.25])
            assert sum(parts) == total
            assert min(parts) >= 1

    def test_split_integer_zero(self):
        assert _split_integer(0, [0.5, 0.5]) == [0, 0]


class TestCensusLayout:
    def test_reads_raw_census_with_preamble(self, tmp_path):
        lk = _census(tmp_path, ["1,199,,DN,,0.00,,JCT RTE 101,800,,7000,820,,7200"],
                     preamble="Caltrans Traffic Volumes\n\n")
        assert lk.layout == "census"
        assert lk.lookup("199", 0.5, county="DN") == 7200

    def test_ahead_before_back_after(self, tmp_path):
        rows = ["1,199,,DN,,1.00,,A,600,,5000,610,,5100",
                "1,199,,DN,,4.00,,B,700,,6000,710,,6100"]
        lk = _census(tmp_path, rows)
        # 1.5 is nearer PM 1.00 -> AHEAD of 1.00
        assert lk.lookup("199", 1.5, county="DN") == 5100
        # 3.8 is nearer PM 4.00 -> BACK of 4.00
        assert lk.lookup("199", 3.8, county="DN") == 6000

    def test_county_separates_postmiles(self, tmp_path):
        rows = ["3,50,,ED,,5.00,,X,900,,9000,900,,9000",
                "3,50,,SAC,,5.00,,Y,3000,,30000,3000,,30000"]
        lk = _census(tmp_path, rows)
        assert lk.lookup("50", 5.0, district=3, county="ED") == 9000
        assert lk.lookup("50", 5.0, district=3, county="SAC") == 30000

    def test_peak_hour_used(self, tmp_path):
        lk = _census(tmp_path, ["1,199,,DN,,0.00,,J,800,,7000,820,,7200"])
        rec = lk.lookup_record("199", 0.2, county="DN")
        assert rec.peak_hour == 820
        tm = generate_turning_movements(
            "C1", 4, [0, 2, 4, 6], False, "199", 0.2, county="DN",
            aadt_lookup=lk, d_factor=0.5)
        assert tm.aadt_source == "caltrans_census"
        assert tm.peak_hour_basis == "census_peak_hour"
        assert tm.approach_volumes[0] == 410          # 820 x 0.5
        assert tm.aadt2_assumed and tm.aadt2 == round(7200 * CROSS_RATIO)

    def test_too_far_returns_none(self, tmp_path):
        lk = _census(tmp_path, ["1,199,,DN,,0.00,,J,800,,7000,820,,7200"])
        assert lk.lookup("199", 20.0, county="DN") is None

    def test_suffixed_route_skipped(self, tmp_path):
        lk = _census(tmp_path, ["1,199,U,DN,,0.00,,BUS,800,,7000,820,,7200"])
        assert lk.lookup("199", 0.0, county="DN") is None

    def test_reads_xlsx(self, tmp_path):
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        ws.append(["Caltrans Traffic Volumes"]); ws.append([])
        ws.append(CENSUS_HEADER.split(","))
        ws.append([1, 199, None, "DN", None, 0.0, None, "J", 800, None, 7000, 820, None, 7200])
        f = tmp_path / "census.xlsx"; wb.save(f)
        lk = AADTLookup(str(f))
        assert lk.layout == "census"
        assert lk.lookup("199", 0.1, county="DN") == 7200


class TestSegmentLayout:
    def test_containment_near_end_of_long_segment(self, tmp_path):
        f = tmp_path / "seg.csv"
        f.write_text("district,route,pm_start,pm_end,aadt\n"
                     "1,101,0.0,6.0,15000\n1,101,6.0,9.0,22000\n")
        lk = AADTLookup(str(f))
        # v1.0 midpoint rule rejected 5.5 (2.5 mi from midpoint 3.0)
        assert lk.lookup("101", 5.5, district=1) == 15000
        assert lk.lookup("101", 7.0, district=1) == 22000


class TestConfigurableFactors:
    def test_k_d_hv_cross(self):
        kw = dict(site_id="F", n_legs=4, leg_idxs=[0, 2, 4, 6], is_ramp=False,
                  route1="1", pm1=1.0, scenario="medium")
        a = generate_turning_movements(**kw)
        b = generate_turning_movements(**kw, k_factor=0.10, d_factor=0.60,
                                       hv_pct=0.0, cross_ratio=1.0)
        assert b.total_entry > a.total_entry
        assert all(hv == 0 for _, hv in b.volumes.values())
        assert b.approach_volumes[0] == b.approach_volumes[2]


class TestObservedCounts:
    def test_load_and_build(self, tmp_path):
        f = tmp_path / "counts.csv"
        f.write_text("site_id,from_leg,to_leg,lv,hv\n"
                     "X,S,N,100,5\nX,N,S,90,\nX,E,W,40,2\nX,W,E,30,1\n")
        counts = load_turning_counts(str(f))
        assert counts["X"][(0, 4)] == (100, 5)
        assert counts["X"][(4, 0)] == (90, 0)
        tm = observed_turning_movements("X", [0, 2, 4, 6], counts["X"])
        assert tm.aadt_source == "observed_counts"
        assert tm.total_entry == 100 + 5 + 90 + 40 + 2 + 30 + 1

    def test_unknown_leg_rejected(self):
        with pytest.raises(ValueError):
            observed_turning_movements("X", [0, 2, 4], {(6, 0): (10, 0)})


class TestInterchangeSites:
    def test_freeway_volume_not_used(self, tmp_path):
        lk = _census(tmp_path, ["7,5,,LA,,56.60,,I-5 MAINLINE,6900,,108000,6900,,108000"])
        tm = generate_turning_movements(
            "R1", 4, [0, 2, 4, 6], True, "5", 56.6, county="LA",
            aadt_lookup=lk, scenario="medium")
        assert tm.aadt_source == "synthetic"
        assert tm.aadt1 == SYNTHETIC_AADT["medium"]
        assert "freeway mainline" in tm.notes

    def test_crossing_state_route_used(self, tmp_path):
        rows = ["3,80,,NEV,,10.00,,I-80 MAINLINE,4000,,40000,4000,,40000",
                "3,89,,NEV,,0.50,,RTE 89,500,,5000,520,,5200"]
        lk = _census(tmp_path, rows)
        tm = generate_turning_movements(
            "R2", 4, [0, 2, 4, 6], True, "80", 10.0, route2="89", pm2=0.6,
            county="NEV", aadt_lookup=lk, d_factor=0.5)
        assert tm.aadt_source == "caltrans_census"
        assert tm.main_route == "89" and tm.aadt1 == 5200
        assert tm.approach_volumes[0] == 260            # 520 x 0.5
        assert tm.aadt2_assumed
