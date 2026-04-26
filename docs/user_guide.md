# User Guide: SIDRA Calibration Tool for California Roundabouts

**Version:** 1.0  
**Project:** SIDRA Calibration for Roundabouts in California  
**Prepared by:** A. Kurzhanskiy, A. Skabardonis — UC Berkeley PATH  
**Sponsor:** California Department of Transportation (Caltrans)  
**Repository:** https://github.com/ucbtrans/sidra-calibration

---

## Introduction

This user guide describes how to install, configure, and use the SIDRA Calibration Tool — a Python-based pipeline that automates roundabout capacity analysis and model calibration using SIDRA Intersection v10.

The tool is designed for Caltrans engineers and external partners who:
- Perform SIDRA roundabout analysis on the California State Highway System (SHS)
- Need to calibrate the SIDRA Environment Factor (fe) to local conditions
- Want consistent, reproducible calibration across multiple sites

**What the tool does:**
1. Fetches roundabout geometry from OpenStreetMap
2. Estimates peak-hour turning movements from Caltrans AADT data
3. Builds and runs SIDRA models automatically via the SIDRA v10 Python API
4. Sweeps the Environment Factor across its full range (0.5–2.0) and records capacity, delay, and LOS
5. Calibrates fe to observed field capacity (when field data are available)
6. Generates formatted Excel reports

---

## Part 1: Installation

### System Requirements

| Requirement | Details |
|---|---|
| Operating System | Windows 10 or 11 (64-bit) |
| SIDRA Intersection | Version 10 (licensed installation required) |
| Python | Version 3.10 or later |
| Internet access | Required for first-run OSM geometry download |
| Disk space | ~100 MB for tool + ~500 MB for generated .sipx files (58 sites) |

### Step 1 — Install Python

If Python is not already installed:

1. Go to https://www.python.org/downloads/
2. Download the latest Python 3.x Windows installer
3. Run the installer — check **"Add Python to PATH"** before clicking Install
4. Verify: open Command Prompt and type `python --version`

### Step 2 — Download the tool

**Option A — Download ZIP (no git required):**
1. Go to https://github.com/ucbtrans/sidra-calibration
2. Click **Code → Download ZIP**
3. Extract to a folder such as `C:\SIDRACalibration\`

**Option B — Clone with git:**
```
git clone https://github.com/ucbtrans/sidra-calibration.git C:\SIDRACalibration
```

### Step 3 — Install Python dependencies

Open Command Prompt, navigate to the tool folder, and run:

```
cd C:\SIDRACalibration
pip install -r requirements.txt
```

This installs:
- `pythonnet` — connects Python to the SIDRA .NET API
- `osmnx` — downloads roundabout geometry from OpenStreetMap
- `openpyxl` — writes Excel reports
- `deap` — Genetic Algorithm optimization (optional, for multi-parameter calibration)

**Troubleshooting:** If `pip install` fails with a permissions error, use:
```
pip install --user -r requirements.txt
```

### Step 4 — Verify SIDRA is installed

The tool requires SIDRA Intersection v10 to be installed on the same computer. Verify by opening SIDRA Intersection from the Start menu. The tool will automatically find the SIDRA API at its default installation path.

If SIDRA is installed in a non-standard location, set the environment variable:
```
set SIDRA_PATH=C:\Path\To\SIDRA\Installation
```

### Step 5 — Verify installation

Run the following command to confirm everything is working:
```
cd C:\SIDRACalibration
python run_calibration.py --sites 1
```

Expected output:
```
Loading sites from data/sites.csv ...
  Loaded 58 open roundabout sites.
  Processing first 1 sites.

Processing site D01-DN-199-6: Route 199 at Elk Valley Cross Road
  Fetching geometry from OSM ...
  Geometry: OSM node 84952534; 3 legs extracted.
  Generating turning movements ...
  Baseline processed. 3 lanes.
  Running sensitivity sweep (16 steps) ...
  Sweep complete: 16 points.

Writing site report to output/site_results.xlsx ...
Done.
```

---

## Part 2: Running the Tool

### Basic usage

**Process all 58 open sites on the California SHS:**
```
python run_calibration.py
```

**Process only the first N sites (for testing):**
```
python run_calibration.py --sites 5
```

**Use a different volume scenario:**
```
python run_calibration.py --scenario low      # AADT ~5,000/day
python run_calibration.py --scenario medium   # AADT ~12,000/day (default)
python run_calibration.py --scenario high     # AADT ~25,000/day
```

**Change the number of sweep steps:**
```
python run_calibration.py --steps 32
```

### Calibration with observed field data

When you have measured entry capacity from field counts:
```
python run_calibration.py --observed-capacity 1200
```

This runs the bisection algorithm to find the fe value that reproduces 1,200 veh/h entry capacity at each site. The calibrated fe is reported in the Excel output.

### Command-line options summary

| Option | Default | Description |
|---|---|---|
| `--sites N` | all | Process only first N sites |
| `--scenario` | medium | Synthetic volume level (low/medium/high) |
| `--param` | fe | Parameter to sweep: `fe` or `cf` |
| `--steps N` | 16 | Number of steps in sensitivity sweep |
| `--observed-capacity X` | none | Target capacity for bisection calibration (veh/h) |

---

## Part 3: Adding AADT Data

By default, the tool uses synthetic traffic volumes. For more accurate analysis, provide real Caltrans AADT data.

### Step 1 — Download AADT data

1. Go to https://dot.ca.gov/programs/traffic-operations/census
2. Download the **Annual Average Daily Traffic (AADT)** data for the relevant district(s)
3. Export to CSV format with at least these columns: `district`, `route`, `pm_start`, `pm_end`, `aadt`

### Step 2 — Place the file

Save the CSV as:
```
C:\SIDRACalibration\data\aadt\ca_route_aadt.csv
```

### Step 3 — Re-run

Run the tool again. It will automatically use the AADT file if found:
```
python run_calibration.py
```

The `AADT Source` column in the Excel output will show `caltrans_census` instead of `synthetic`.

---

## Part 4: Understanding the Output

The tool writes two Excel files to the `output/` folder.

### site_results.xlsx

One worksheet per site. Each sheet contains:

**Site Information** — ID, district, county, route, location, coordinates, lane configuration, AADT

**Geometry** — Leg-by-leg table with entry lanes, exit lanes, circulating lanes, circulating width, and data source (OSM or defaults)

**Sensitivity Analysis — Environment Factor (fe)** — The main results table:

| Column | Description |
|---|---|
| Environment Factor (fe) | The parameter value (0.5 to 2.0) |
| Avg Capacity (veh/h) | Mean entry capacity across all approach lanes |
| Min Capacity | Minimum across lanes |
| Max Capacity | Maximum across lanes |
| Avg Deg. Satn (v/c) | Mean degree of saturation |
| Avg Delay (s/veh) | Mean control delay per vehicle |

A line chart of capacity vs. fe is embedded in each sheet.

**Lane Outputs (default parameters)** — Per-lane detail at the default fe (1.05):

| Column | Description |
|---|---|
| Leg / Lane | Approach name and lane number |
| Flow (veh/h) | Demand volume entering |
| Capacity (veh/h) | SIDRA estimated entry capacity |
| Deg. Satn (v/c) | Volume-to-capacity ratio |
| Ctrl Delay (s/veh) | Average control delay |
| LOS | Level of Service (A–F) |
| 95th Queue (veh) | 95th percentile back-of-queue |

### summary.xlsx

A single-sheet cross-site summary with one row per site:

| Column | Description |
|---|---|
| Default Cap. (veh/h) | Entry capacity at fe = 1.05 |
| Cap. @ fe=0.9 | Capacity at fe = 0.9 (upper end of recommended range) |
| Cap. @ fe=1.1 | Capacity at fe = 1.1 |
| Ctrl Delay @ default | Control delay at fe = 1.05 |
| LOS @ default | Level of Service at fe = 1.05 |

---

## Part 5: Calibration Guidance

### Recommended default (no field data)

Use **fe = 1.05** for all California SHS roundabouts. This is the SIDRA Standard US HCM default for single-lane roundabouts and produces results consistent with HCM 6th Edition guidance.

### When to adjust fe

| Condition | Recommended fe |
|---|---|
| Default (no site-specific data) | 1.05 |
| Urban site, high pedestrian activity, restricted geometry | 1.2–1.3 |
| Rural site, good sight distance, simple geometry | 0.9–1.0 |
| High heavy vehicle percentage (>10%) | Increase by 0.1–0.2 |

**Do not use fe outside the range 0.8–1.5** without supporting field calibration data.

### Calibration with field data

When you have field-measured entry capacity (from turning movement counts at or near saturation):

1. Identify the site's observed entry capacity (veh/h) from field data
2. Run: `python run_calibration.py --observed-capacity [value]`
3. The tool reports the calibrated fe for each site
4. The calibrated fe should fall in the range 0.8–1.5; if not, review the field data or geometry inputs

The bisection algorithm converges to within ±0.5% of the target capacity in 10–15 SIDRA runs.

### Geometry accuracy

Geometry inputs (inscribed diameter, circulating width, entry angle) have a larger effect on estimated capacity than fe. Before relying on calibrated fe values:

1. Verify inscribed diameter against aerial imagery or design plans
2. Confirm number of entry and circulating lanes
3. Update `data/sites.csv` if the geometry differs significantly from defaults

---

## Part 6: Running Tests

The test suite verifies that the tool's core logic is working correctly. Run before submitting results to Caltrans:

```
cd C:\SIDRACalibration
python -m pytest tests/ -v
```

Expected output: **65 passed** (tests for calibration engine, geometry, volumes, and site loading). Tests run without requiring SIDRA to be active.

---

## Part 7: Troubleshooting

### "SIDRA API not available"

The tool cannot find the SIDRA v10 DLL. Check that:
- SIDRA Intersection v10 is installed (not v9.1)
- You are running on Windows
- The SIDRA API DLL is registered (re-run the SIDRA installer if needed)

### "OSM geometry not found"

The tool cannot locate a roundabout in OpenStreetMap at the site coordinates. Check that:
- The site coordinates in `data/sites.csv` are correct
- The roundabout is mapped in OSM (verify at https://www.openstreetmap.org)
- Your internet connection is working

The tool automatically falls back to default geometry values if OSM fails.

### "SIDRA processing failed — Error #271"

Lane disciplines were not assigned correctly. This is an internal API issue. Contact the project team at akurzhan@gmail.com.

### "Error #304: Flow proportions do not add up to 100%"

This can occur when adding or removing legs manually. Re-run the pipeline from scratch for the affected site.

### Large output files

Each `.sipx` SIDRA project file is approximately 1–2 MB. For 58 sites, the `sites/` folder will be ~100 MB. These files are excluded from git by `.gitignore` and do not need to be backed up (they are regenerated each run).

---

## Part 8: Updating the Site List

The site inventory is stored in `data/sites.csv`. When Caltrans adds new roundabouts to the SHS:

1. Open `data/sites.csv` in Excel
2. Add a new row following the existing format (see column headers in rows 4–5)
3. Set the `Status` column to the year of opening (e.g., `2026`)
4. Enter the latitude and longitude from Google Maps or Caltrans GIS
5. Save as CSV (UTF-8)
6. Re-run the pipeline

New sites will be automatically processed on the next run.

---

## Appendix A: Column Reference for sites.csv

| Column | Description | Example |
|---|---|---|
| Status or Year Opened | Year (open) or "In Constr" / "Out to Bid" | 2022 |
| District | Caltrans district number | 1 |
| County | County code | DN |
| Route 1 | Primary state route | 199 |
| PM 1 | Postmile on Route 1 | 0.8 |
| # of Legs | Number of roundabout legs | 3 |
| Location Description | Text description | Route 199 at Elk Valley Cross Road |
| Latitude | WGS84 decimal degrees | 41.807824 |
| Longitude | WGS84 decimal degrees | -124.147525 |
| Single Lane | Mark "x" if single-lane | x |
| 1 & 2 Lane | Mark "x" if hybrid | |
| 2 or 2+ Lane | Mark "x" if multi-lane | |

---

## Appendix B: Calibration Parameter Reference

| Parameter | Model | Range | Default (US) | Effect |
|---|---|---|---|---|
| Environment Factor (fe) | SIDRA Standard | 0.5–2.0 | 1.05 | Higher fe = lower capacity |
| Model Calibration Factor (cf) | HCM 6th Edition | 0.5–2.0 | 1.0 | Higher cf = lower capacity |

Both parameters adjust critical gap (tc) and follow-up headway (tf) — the fundamental gap acceptance inputs. They should not be set outside the range 0.8–1.5 without field data support.

---

## Appendix C: Contacts

| Role | Name | Email |
|---|---|---|
| Principal Investigator | Alexander Kurzhanskiy | akurzhan@gmail.com |
| Co-PI | Alexander Skabardonis | — |
| Repository | github.com/ucbtrans/sidra-calibration | — |
