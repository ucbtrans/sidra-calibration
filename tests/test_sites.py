"""
Tests for sites.py — site list loader and parser.
No external dependencies required (no SIDRA, no OSM).
"""

import csv
import tempfile
import os
import pytest
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from sites import load_sites, _is_open, Site


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
HEADER_ROWS = [
    "Caltrans Roundabout Status Report,,,,,,,,,,",
    "For questions contact...,,,,,,,,,,,",
    "Note 1,,Note 2,,,,,,,Note 3,,,,,Note 4,,,,Note 5",
    "Status or Year Opened,Project,Lead,District,County,Route 1,PM 1,Route 2,PM 2,# of,,,,,Nearest,Latitude,Longitude,,,Single Lane,1 & 2 Lane,2 or 2+ Lane",
    ",EA,Agency,,,,,,,Legs,,,,,City / Town,,,,,,,",
]

def _make_csv(rows, tmp_path):
    path = os.path.join(tmp_path, "sites.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        for row in HEADER_ROWS:
            writer.writerow(row.split(","))
        for row in rows:
            writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
# _is_open
# ---------------------------------------------------------------------------
class TestIsOpen:
    def test_year_is_open(self):
        assert _is_open("2022") is True
        assert _is_open("2005") is True
        assert _is_open("2019") is True

    def test_in_constr_not_open(self):
        assert _is_open("In Constr") is False
        assert _is_open("Out to Bid") is False
        assert _is_open("") is False

    def test_notes_not_open(self):
        assert _is_open("Notes:") is False


# ---------------------------------------------------------------------------
# load_sites
# ---------------------------------------------------------------------------
class TestLoadSites:
    def test_loads_open_sites(self, tmp_path):
        rows = [
            ["2022","01-0L990","Caltrans","1","DN","199","0.8","","","4","Elk Valley","","","Route 199 at Elk Valley","Crescent City","41.807824","-124.147525","","","x","","",""],
            ["2005","","Local","1","HUM","101","88.8","","","4","Giuntoli","","","SB Ramps","Arcata","40.904","-124.0892","","","x","","",""],
        ]
        path = _make_csv(rows, str(tmp_path))
        sites = load_sites(path, status_filter="open")
        assert len(sites) == 2

    def test_excludes_in_construction(self, tmp_path):
        rows = [
            ["2022","","","1","DN","199","0.8","","","4","","","","Open site","City","41.0","-124.0","","","x","","",""],
            ["In Constr","","","1","HUM","101","88.0","","","4","","","","Under constr","City","40.0","-124.0","","","x","","",""],
        ]
        path = _make_csv(rows, str(tmp_path))
        sites = load_sites(path, status_filter="open")
        assert len(sites) == 1
        assert sites[0].status == "2022"

    def test_status_all_includes_construction(self, tmp_path):
        rows = [
            ["2022","","","1","DN","199","0.8","","","4","","","","Open site","City","41.0","-124.0","","","x","","",""],
            ["In Constr","","","1","HUM","101","88.0","","","4","","","","Under constr","City","40.0","-124.0","","","x","","",""],
        ]
        path = _make_csv(rows, str(tmp_path))
        sites = load_sites(path, status_filter="all")
        assert len(sites) == 2

    def test_excludes_missing_coords(self, tmp_path):
        rows = [
            ["2022","","","1","DN","199","0.8","","","4","","","","No coords","City","","","","","x","","",""],
        ]
        path = _make_csv(rows, str(tmp_path))
        sites = load_sites(path, status_filter="open")
        assert len(sites) == 0

    def test_lane_config_single(self, tmp_path):
        rows = [
            ["2022","","","1","DN","199","0.8","","","4","","","","Site","City","41.0","-124.0","","","x","","",""],
        ]
        path = _make_csv(rows, str(tmp_path))
        sites = load_sites(path)
        assert sites[0].lane_config == "single_lane"

    def test_lane_config_hybrid(self, tmp_path):
        rows = [
            ["2022","","","1","DN","199","0.8","","","4","","","","Site","City","41.0","-124.0","","","","x","",""],
        ]
        path = _make_csv(rows, str(tmp_path))
        sites = load_sites(path)
        assert sites[0].lane_config == "hybrid"

    def test_lane_config_two_lane(self, tmp_path):
        rows = [
            ["2022","","","1","DN","199","0.8","","","4","","","","Site","City","41.0","-124.0","","","","","x",""],
        ]
        path = _make_csv(rows, str(tmp_path))
        sites = load_sites(path)
        assert sites[0].lane_config == "two_lane"

    def test_is_ramp_detection(self, tmp_path):
        rows = [
            ["2022","","","1","HUM","101","88.0","","","4","","","","SB Route 101 Ramps at Giuntoli","Arcata","40.9","-124.0","","","x","","",""],
            ["2022","","","1","DN","199","0.8","","","4","","","","Route 199 at Elk Valley","Crescent City","41.8","-124.1","","","x","","",""],
        ]
        path = _make_csv(rows, str(tmp_path))
        sites = load_sites(path)
        assert sites[0].is_ramp is True
        assert sites[1].is_ramp is False

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_sites("/nonexistent/path/sites.csv")

    def test_real_sites_csv(self):
        real_csv = os.path.join(os.path.dirname(__file__), '..', 'data', 'sites.csv')
        if not os.path.exists(real_csv):
            pytest.skip("data/sites.csv not found")
        sites = load_sites(real_csv, status_filter="open")
        assert len(sites) >= 50
        assert all(isinstance(s, Site) for s in sites)
        assert all(s.lat != 0 and s.lon != 0 for s in sites)
        assert all(s.lane_config in ("single_lane", "hybrid", "two_lane") for s in sites)
