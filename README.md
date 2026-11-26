# SIDRA Calibration Tool for California Roundabouts

A calibration pipeline for SIDRA Intersection v10 roundabout capacity models on the California State Highway System (SHS).

We developed it at [University of California, Berkeley PATH](https://path.berkeley.edu/) under a Caltrans research contract.

---

## Overview

The tool runs the SIDRA roundabout calibration workflow from start to finish:

1. Geometry comes from the OpenStreetMap (OSM) cache shipped with the tool, from live OSM, or from design defaults.
2. Volumes are observed turning counts, or planning-level peak-hour movements estimated from the Caltrans Traffic Census.
3. SIDRA Intersection v10 models are built and run through the Python API.
4. One or more calibration parameters are swept across their feasible ranges.
5. The parameters are fitted to observed field targets by minimizing a weighted normalized error.
6. Results are written out as tables, sweep plots and error/capacity heatmaps.

## Calibration parameters and targets

The framework works with seven input calibration parameters:

| # | Parameter | Model | Status |
|---|-----------|-------|--------|
| 1 | Environment Factor (fe) | SIDRA Standard US | Ready |
| 2 | Model Calibration Factor (cf) | HCM 2010, HCM 6 | Ready |
| 3 | Entry-Circulating Flow Adjustment | SIDRA Standard US | Ready |
| 4 | Gap Acceptance Factor | All | Field data + probe |
| 5 | Opposing Vehicle Factor | All | Field data + probe |
| 6 | Lane Utilization Ratio | Multi-lane sites | Field data + probe |
| 7 | Extra Bunching Parameter | Signal-adjacent sites | Field data + probe |

and four output targets:

| # | Target | Saturation needed | Model |
|---|--------|-------------------|-------|
| 1 | Entry capacity C (veh/h per lane) | Yes | All |
| 2 | 95th percentile queue Q95 (vehicles) | Yes | All |
| 3 | Average control delay d (s/veh) | Yes | All |
| 4 | Critical gap tc and follow-up headway tf (s) | No | SIDRA Standard US only |

## Requirements

- Windows (SIDRA Intersection v10 runs only on Windows)
- SIDRA Intersection v10, licensed and installed
- Python 3.9 or later

Install the Python dependencies:

```bash
pip install -r requirements.txt
```

`requirements.txt` lists `pythonnet`, `osmnx`, `openpyxl`, `deap`, `python-docx`, `pyyaml`, `matplotlib` and `numpy`.

## Quick Start

### Phase 1 - single-parameter, multi-target calibration

`calibrate_site.py` sweeps one parameter (fe or cf) and picks the value that best matches all the field targets you specify, measured by weighted normalized error. The run is set up in a YAML file.

```bash
cd sidra-calibration
python calibrate_site.py configs/example_site.yaml
```

Output (`output/calibration/{site_id}/`):
- `results.json` - full sweep, best-fit value, residuals per target
- `sweep_plot.png` - model outputs and combined error curve vs the parameter

### Phase 2 - two-parameter grid search

`calibrate_grid.py` sweeps any two parameters on a grid and finds the pair with the lowest weighted error. You choose the two parameters in the YAML config.

```bash
python calibrate_grid.py configs/example_grid.yaml
```

Output (`output/calibration/{site_id}/grid_{p1}_{p2}/`):
- `grid_results.json` - full error surface
- `heatmap.png` - error and capacity surfaces with best-fit marker

### Phase 3 - genetic algorithm (three or more parameters)

With more than two parameters a full grid grows exponentially, so `calibrate_ga.py` uses a genetic algorithm with a fixed evaluation budget instead. The parameters to calibrate are listed in the YAML config.

```bash
python calibrate_ga.py configs/example_ga.yaml
```

Output (`output/calibration/{site_id}/ga_{params}/`):
- `ga_results.json` - best parameters, residuals, convergence history
- `convergence.png` - best/mean error vs generation, per-target residuals

The GA engine (`src/genetic_search.py`) uses only the Python standard library, so it needs no third-party optimization package. Each fitness evaluation is a SIDRA run. The engine caches results by parameter values, so each distinct combination runs at most once.

### Batch screening and single-target calibration

```bash
python run_calibration.py                                # all sites, SIDRA Standard US (fe)
python run_calibration.py --site-id D03-PLA-89-28        # one site
python run_calibration.py --model hcm6                   # HCM 6, sweeps cf
python run_calibration.py --model hcm6 --observed examples/observed_capacity_example.csv \
                          --counts examples/turning_counts_example.csv
```

Each site is built from `templates/us_roundabout_template.sipx` (US HCM Customary, right-hand traffic). All options are described in `docs/user_guide.md`.

### Choosing a tool

| Parameters | Tool | Method |
|-----------|------|--------|
| 1 | `calibrate_site.py` | Exhaustive sweep |
| 2 | `calibrate_grid.py` | Exhaustive 2D grid |
| 3 or more | `calibrate_ga.py` | Genetic algorithm |

## Project Structure

```
sidra-calibration/
├── calibrate_site.py       # Phase 1 - single-parameter multi-target
├── calibrate_grid.py       # Phase 2 - two-parameter grid search
├── calibrate_ga.py         # Phase 3 - genetic algorithm (3+ parameters)
├── run_calibration.py      # Batch screening sweep + per-site bisection
├── requirements.txt
├── CHANGELOG.md
├── templates/
│   └── us_roundabout_template.sipx  # US HCM (Customary) base site
├── examples/               # Example observed-capacity and turning-count CSVs
├── configs/
│   ├── example_site.yaml   # Phase 1 config template
│   ├── example_grid.yaml   # Phase 2 config template
│   └── example_ga.yaml     # Phase 3 config template
├── data/
│   ├── sites.csv           # Caltrans SHS roundabout inventory
│   └── aadt/               # Place the census file here (see below)
├── osm/
│   └── parsed.json         # Cached OSM geometry (used by default, no network)
├── src/
│   ├── sidra_api.py        # SIDRA v10 Python API wrapper
│   ├── geometry.py         # OSM geometry extraction
│   ├── volumes.py          # Peak-hour volume estimation
│   ├── calibration.py      # Legacy sensitivity sweep + bisection
│   ├── multi_target.py     # Weighted normalized error, parameter sweep
│   ├── grid_search.py      # 2D grid search over two parameters
│   ├── genetic_search.py   # Genetic algorithm over N parameters
│   ├── param_registry.py   # Registry of the seven calibration parameters
│   ├── sites.py            # Site list loader
│   └── report.py           # Excel report writer
├── probe_*.py              # SIDRA .NET API property discovery scripts
├── sites/                  # Generated .sipx SIDRA project files
└── output/                 # Generated reports and plots
```

## Site Inventory

The tool processes the open roundabouts on the California SHS listed in the Task 2 site inventory (`data/sites.csv`). They are spread over Caltrans districts across the state.

The cached geometry in `osm/parsed.json` is derived from OpenStreetMap data, © OpenStreetMap contributors, available under the Open Database License (ODbL).

## AADT Data

For screening runs with real volumes, download the Caltrans Traffic Census (Traffic Volumes) file from the [Caltrans Traffic Data Branch](https://dot.ca.gov/programs/traffic-operations/census) and save it, unchanged, at:

```
data/aadt/ca_route_aadt.csv   (or .xlsx)
```

The tool reads the published layout (RTE, CNTY, PM, BACK_/AHEAD_PEAK_HOUR, BACK_/AHEAD_AADT ...) as is. Sites are matched on route, county and postmile, and the census peak-hour volume is used when it is available. The older segment layout (`district, route, pm_start, pm_end, aadt`) also still works.

Sites with no census match get synthetic volumes. K (0.09), D (0.55), heavy vehicle share (6%) and the cross-road ratio (50%) are planning defaults; you can change each of them on the command line. For calibration, use observed turning counts (`--counts`).

## Calibration Method

Calibration adjusts the chosen input parameters until the model outputs match the observed field targets. The objective is the weighted normalized squared error

```
E = sum_i w_i * ((y_modeled_i - y_target_i) / y_target_i)^2 / sum_i w_i
```

taken over the targets you specify (capacity, queue, delay). Phase 1 minimizes E over a single parameter, Phase 2 over a two-parameter grid, and Phase 3 uses a genetic algorithm for three or more parameters at once.

Default parameter ranges:

- Environment Factor (fe), SIDRA Standard US: 0.5 to 2.0 (US single-lane default 1.05)
- Model Calibration Factor (cf), HCM 2010 / HCM 6: 0.7 to 1.3

Capacity, queue and delay targets need near-saturation conditions in the field. Critical gap and follow-up headway can be measured from video without saturation, and they apply only to the SIDRA Standard US model.

## Citation

Kurzhanskiy, A., and Skabardonis, A. (2026). *SIDRA Calibration Tool for California Roundabouts*. University of California, Berkeley, PATH. https://github.com/ucbtrans/sidra-calibration

## License

MIT License. See [LICENSE](LICENSE).
