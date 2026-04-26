# SIDRA Calibration Tool for California Roundabouts

Automated calibration pipeline for SIDRA Intersection v10 roundabout capacity models on the California State Highway System (SHS).

Developed by the [University of California, Berkeley PATH](https://path.berkeley.edu/) under Caltrans research contract.

---

## Overview

This tool automates the SIDRA roundabout model calibration workflow:

1. **Geometry extraction** — downloads roundabout geometry from OpenStreetMap (OSM)
2. **Volume estimation** — estimates peak-hour turning movements from Caltrans AADT
3. **SIDRA modeling** — builds and runs SIDRA Intersection v10 models via the Python API
4. **Sensitivity sweep** — sweeps the Environment Factor (fe) across its feasible range (0.5–2.0)
5. **Calibration** — fits fe to observed field capacity using bisection search
6. **Reporting** — writes Excel workbooks with capacity, delay, LOS, and queue results

## Requirements

- **Windows** (SIDRA Intersection v10 is Windows-only)
- **SIDRA Intersection v10** installed (license required)
- **Python 3.10+**

Install Python dependencies:

```bash
pip install -r requirements.txt
```

`requirements.txt` includes: `pythonnet`, `osmnx`, `openpyxl`, `deap`, `python-docx`

## Quick Start

### Run sensitivity sweep on all sites

```bash
cd sidra-calibration
python run_calibration.py
```

### Run on first N sites only (for testing)

```bash
python run_calibration.py --sites 3
```

### Run with a specific parameter sweep

```bash
python run_calibration.py --param fe      # Environment Factor (default)
python run_calibration.py --param cf      # HCM6 Calibration Factor
```

Output is written to:
- `output/site_results.xlsx` — one sheet per site with sweep table and chart
- `output/summary.xlsx` — cross-site summary (capacity, delay, LOS at default fe)

## Project Structure

```
sidra-calibration/
├── run_calibration.py     # Main entry point
├── requirements.txt
├── data/
│   ├── sites.csv          # Caltrans SHS roundabout inventory
│   └── aadt/              # Place ca_route_aadt.csv here (see below)
├── src/
│   ├── sidra_api.py       # SIDRA v10 Python API wrapper
│   ├── geometry.py        # OSM geometry extraction
│   ├── volumes.py         # Peak-hour volume estimation
│   ├── calibration.py     # Sensitivity sweep and bisection calibration
│   ├── sites.py           # Site list loader
│   └── report.py          # Excel report writer
├── sites/                 # Generated .sipx SIDRA project files
└── output/                # Generated Excel reports
```

## Site Inventory

The tool processes 58 open roundabouts on the California SHS identified in the Task 2 site inventory (`data/sites.csv`). Sites span 11 Caltrans districts across the state.

## AADT Data

For real traffic volumes, download the Caltrans Traffic Census AADT CSV from the [Caltrans Traffic Data Branch](https://dot.ca.gov/programs/traffic-operations/census) and place it at:

```
data/aadt/ca_route_aadt.csv
```

Required columns: `district`, `route`, `pm_start`, `pm_end`, `aadt`

Without this file, the tool uses synthetic volumes (K=0.09, D=0.55).

## Calibration Method

The primary calibration parameter is the **Environment Factor (fe)**:

- Range: 0.5–2.0
- Default (US single-lane): 1.05
- Recommended range for California SHS: 0.9–1.3

When observed field capacity is available, the bisection algorithm identifies the fe value that minimizes model error (target: ±5% of observed capacity).

## Research Context

This tool was developed as part of the Caltrans research project **"SIDRA Calibration for Roundabouts in California"** (7-task SOW, UC Berkeley PATH). Key tasks:

| Task | Description | Status |
|------|-------------|--------|
| 2 | Operational Review of SIDRA Model | Complete |
| 3 | Calibration Methodology | Complete |
| 4 | Application of SIDRA Model (Working Paper) | Complete |
| 5 | Development of SIDRA Calibration Tool | This repository |
| 6 | Draft Final Report | In progress |
| 7 | Final Report and Workshop | In progress |

## Citation

Kurzhanskiy, A., and Skabardonis, A. (2026). *SIDRA Calibration Tool for California Roundabouts*. University of California, Berkeley, PATH. https://github.com/ucbtrans/sidra-calibration

## License

MIT License. See [LICENSE](LICENSE).
