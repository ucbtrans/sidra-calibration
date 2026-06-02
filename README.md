# SIDRA Calibration Tool for California Roundabouts

Automated calibration pipeline for SIDRA Intersection v10 roundabout capacity models on the California State Highway System (SHS).

Developed by the [University of California, Berkeley PATH](https://path.berkeley.edu/) under Caltrans research contract.

---

## Overview

This tool automates the SIDRA roundabout model calibration workflow:

1. **Geometry extraction** - downloads roundabout geometry from OpenStreetMap (OSM)
2. **Volume estimation** - estimates peak-hour turning movements from Caltrans AADT
3. **SIDRA modeling** - builds and runs SIDRA Intersection v10 models via the Python API
4. **Parameter sweep** - sweeps one or more calibration parameters across their feasible ranges
5. **Calibration** - fits parameters to observed field targets by minimizing weighted normalized error
6. **Reporting** - writes result tables, sweep plots, and error/capacity heatmaps

## Calibration parameters and targets

The framework recognizes **seven input calibration parameters**:

| # | Parameter | Model | Status |
|---|-----------|-------|--------|
| 1 | Environment Factor (fe) | SIDRA Standard US | Ready |
| 2 | Model Calibration Factor (cf) | HCM 2010, HCM 6 | Ready |
| 3 | Entry-Circulating Flow Adjustment | All | API probe needed |
| 4 | Gap Acceptance Factor | All | Field data + probe |
| 5 | Opposing Vehicle Factor | All | Field data + probe |
| 6 | Lane Utilization Ratio | Multi-lane sites | Field data + probe |
| 7 | Extra Bunching Parameter | Signal-adjacent sites | Field data + probe |

and **four output calibration targets**:

| # | Target | Saturation needed | Model |
|---|--------|-------------------|-------|
| 1 | Entry capacity C (veh/h per lane) | Yes | All |
| 2 | 95th percentile queue Q95 (vehicles) | Yes | All |
| 3 | Average control delay d (s/veh) | Yes | All |
| 4 | Critical gap tc and follow-up headway tf (s) | No | SIDRA Standard US only |

## Requirements

- **Windows** (SIDRA Intersection v10 is Windows-only)
- **SIDRA Intersection v10** installed (license required)
- **Python 3.10+**

Install Python dependencies:

```bash
pip install -r requirements.txt
```

`requirements.txt` includes: `pythonnet`, `osmnx`, `openpyxl`, `deap`, `python-docx`, `pyyaml`, `matplotlib`, `numpy`

## Quick Start

### Phase 1 - single-parameter, multi-target calibration

Sweeps one parameter (fe or cf) and finds the value that best matches all
specified field targets by weighted normalized error. Configured by YAML.

```bash
cd sidra-calibration
python calibrate_site.py configs/example_site.yaml
```

Output (`output/calibration/{site_id}/`):
- `results.json` - full sweep, best-fit value, residuals per target
- `sweep_plot.png` - model outputs and combined error curve vs the parameter

### Phase 2 - two-parameter grid search

Sweeps any two user-selectable parameters on a grid and finds the combination
that minimizes weighted error. Parameters are chosen in the YAML config.

```bash
python calibrate_grid.py configs/example_grid.yaml
```

Output (`output/calibration/{site_id}/grid_{p1}_{p2}/`):
- `grid_results.json` - full error surface
- `heatmap.png` - error and capacity surfaces with best-fit marker

### Batch sensitivity sweep (legacy single-target)

```bash
python run_calibration.py            # all sites
python run_calibration.py --sites 3  # first 3 sites only
python run_calibration.py --param fe # or --param cf
```

## Project Structure

```
sidra-calibration/
├── calibrate_site.py       # Phase 1 - single-parameter multi-target
├── calibrate_grid.py       # Phase 2 - two-parameter grid search
├── run_calibration.py      # Legacy batch sensitivity sweep
├── requirements.txt
├── configs/
│   ├── example_site.yaml   # Phase 1 config template
│   └── example_grid.yaml   # Phase 2 config template
├── data/
│   ├── sites.csv           # Caltrans SHS roundabout inventory
│   └── aadt/               # Place ca_route_aadt.csv here (see below)
├── src/
│   ├── sidra_api.py        # SIDRA v10 Python API wrapper
│   ├── geometry.py         # OSM geometry extraction
│   ├── volumes.py          # Peak-hour volume estimation
│   ├── calibration.py      # Legacy sensitivity sweep + bisection
│   ├── multi_target.py     # Weighted normalized error, parameter sweep
│   ├── grid_search.py      # 2D grid search over two parameters
│   ├── param_registry.py   # Registry of the seven calibration parameters
│   ├── sites.py            # Site list loader
│   └── report.py           # Excel report writer
├── probe_*.py              # SIDRA COM property discovery scripts
├── sites/                  # Generated .sipx SIDRA project files
└── output/                 # Generated reports and plots
```

## Site Inventory

The tool processes open roundabouts on the California SHS identified in the Task 2 site inventory (`data/sites.csv`), spanning Caltrans districts across the state.

## AADT Data

For real traffic volumes, download the Caltrans Traffic Census AADT CSV from the [Caltrans Traffic Data Branch](https://dot.ca.gov/programs/traffic-operations/census) and place it at:

```
data/aadt/ca_route_aadt.csv
```

Required columns: `district`, `route`, `pm_start`, `pm_end`, `aadt`

Without this file, the tool uses synthetic volumes (K=0.09, D=0.55).

## Calibration Method

Calibration fits the chosen input parameters so that model outputs match
observed field targets. The objective is the weighted normalized squared error:

```
E = sum_i w_i * ((y_modeled_i - y_target_i) / y_target_i)^2 / sum_i w_i
```

over the specified targets (capacity, queue, delay). Phase 1 minimizes E over a
single parameter; Phase 2 minimizes E over a two-parameter grid. A genetic
algorithm (Phase 3, planned) will extend this to three or more parameters.

Default parameter ranges:

- Environment Factor (fe), SIDRA Standard US: 0.5 to 2.0 (US single-lane default 1.05)
- Model Calibration Factor (cf), HCM 2010 / HCM 6: 0.7 to 1.3

Capacity, queue, and delay targets require near-saturation field conditions.
Critical gap and follow-up headway can be measured from video without
saturation, and apply to the SIDRA Standard US model only.

## Research Context

This tool was developed as part of the Caltrans research project **"SIDRA Calibration for Roundabouts in California"** (7-task SOW, UC Berkeley PATH). Key tasks:

| Task | Description | Status |
|------|-------------|--------|
| 2 | Operational Review of SIDRA Model | Complete |
| 3 | Calibration Methodology | Complete |
| 4 | Application of SIDRA Model (Working Paper) | Complete |
| 5 | Development of SIDRA Calibration Tool | This repository |
| 6 | Draft Final Report | In progress |
| 7 | Final Report and presentation for Caltrans | Due June 2026 |

## Citation

Kurzhanskiy, A., and Skabardonis, A. (2026). *SIDRA Calibration Tool for California Roundabouts*. University of California, Berkeley, PATH. https://github.com/ucbtrans/sidra-calibration

## License

MIT License. See [LICENSE](LICENSE).
