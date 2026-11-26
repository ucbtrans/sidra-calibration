# User Guide: SIDRA Calibration Tool for California Roundabouts

Version: 1.1 (November 2026; see CHANGELOG.md for what changed)  
Project: SIDRA Calibration for Roundabouts in California  
Prepared by: A. Kurzhanskiy and A. Skabardonis, UC Berkeley PATH  
Sponsor: California Department of Transportation (Caltrans)  
Repository: https://github.com/ucbtrans/sidra-calibration

---

## Introduction

This guide explains how to install, set up and run the SIDRA Calibration Tool. The tool is a Python pipeline that builds and runs SIDRA Intersection v10 roundabout models and calibrates them against field data.

We wrote it for Caltrans engineers and partners who run SIDRA roundabout analyses on the California State Highway System (SHS), need to calibrate the SIDRA Environment Factor (fe) or the HCM Model Calibration Factor (cf) to local conditions, and want the same procedure applied the same way at every site.

What the tool does:
1. Takes roundabout geometry from the OpenStreetMap (OSM) cache shipped with the tool, from live OSM, or from design defaults
2. Uses observed turning counts when you supply them; otherwise it estimates planning-level peak-hour turning movements from the Caltrans Traffic Census
3. Builds and runs SIDRA models through the SIDRA v10 Python API, using the US HCM (Customary) template in `templates/`
4. Selects the capacity model (SIDRA Standard US, HCM 2010 or HCM 6), sweeps its calibration parameter (fe or cf) and records capacity, delay and LOS
5. Calibrates that parameter to observed field capacity, site by site, when field data are available
6. Writes the results to Excel

Which script to use:

| Task | Script |
|---|---|
| Screening or sensitivity runs over many sites | `run_calibration.py` (this guide) |
| One site, field targets (capacity, Q95, delay), one parameter | `calibrate_site.py` |
| One site, two parameters | `calibrate_grid.py` |
| One site, three or more parameters | `calibrate_ga.py` |

Volumes generated from census data are planning-level inputs for screening. For calibration against field data, use turning counts collected at the same time as the capacity observations (`--counts`, Part 2).

---

## Part 1: Installation

### System Requirements

| Requirement | Details |
|---|---|
| Operating System | Windows 10 or 11 (64-bit) |
| SIDRA Intersection | Version 10 (licensed installation required) |
| Python | Version 3.9 or later |
| Internet access | Not required (OSM cache is included); needed only for `--geometry live` |
| Disk space | About 100 MB for the tool; generated .sipx files are about 60 KB each |

### Step 1: Install Python

If Python is not installed yet:

1. Go to https://www.python.org/downloads/
2. Download the latest Python 3.x Windows installer
3. Run the installer, and check "Add Python to PATH" before you click Install
4. To check it worked, open Command Prompt and type `python --version`

### Step 2: Download the tool

Option A, download a ZIP (no git needed):
1. Go to https://github.com/ucbtrans/sidra-calibration
2. Click Code, then Download ZIP
3. Extract it to a folder such as `C:\SIDRACalibration\`

Option B, clone with git:
```
git clone https://github.com/ucbtrans/sidra-calibration.git C:\SIDRACalibration
```

### Step 3: Install Python dependencies

Open Command Prompt, go to the tool folder and run:

```
cd C:\SIDRACalibration
pip install -r requirements.txt
```

The main packages are `pythonnet` (the link between Python and the SIDRA .NET API), `osmnx` (live OSM downloads), `openpyxl` (Excel reports) and `deap` (optional; only the older GA routine in `src/calibration.py` uses it, while `calibrate_ga.py` needs nothing beyond the standard library).

If `pip install` fails with a permissions error, install into your user folder instead:
```
pip install --user -r requirements.txt
```

### Step 4: Check that SIDRA is installed

SIDRA Intersection v10 has to be installed on the same computer. Open it once from the Start menu to make sure it runs. The tool looks for the SIDRA API in the default installation folder.

If SIDRA is installed somewhere else, set this environment variable:
```
set SIDRA_PATH=C:\Path\To\SIDRA\Installation
```

### Step 5: Test the installation

Run one site:
```
cd C:\SIDRACalibration
python run_calibration.py --sites 1
```

You should see something like this (the volume figures depend on the census file you supply):
```
Capacity model: SIDRA Standard US  parameter: fe [0.5-2.0], default 1.05
Loading sites from data/sites.csv ...
  Loaded 58 open roundabout sites.
  Processing 1 site(s).

Processing site D01-DN-199-6: Route 199 at Elk Valley Cross Road
  Geometry: Not in OSM cache; design defaults used.
  Volumes: synthetic; modeled entry demand ... veh/h
  SIDRA site: US HCM (Customary), capacity model SIDRA Standard US
  Baseline processed. 4 lanes.
  Running sensitivity sweep (16 steps) ...
  Saved D01-DN-199-6.sipx at fe = 1.050

Writing site report to output/site_results.xlsx ...
Done.
```

The line `SIDRA site: US HCM (Customary)` tells you the US template was used. If the template is missing, the tool stops with "SIDRA US template not found". In that case, restore the `templates/` folder from the repository.

---

## Part 2: Running the Tool

### Basic usage

Process all 58 open sites on the California SHS:
```
python run_calibration.py
```

Process only the first N sites (useful for a quick test):
```
python run_calibration.py --sites 5
```

Process specific sites (repeat the option for each one):
```
python run_calibration.py --site-id D03-PLA-89-28 --site-id D04-SCL-152-43
```

Choose the capacity model. The tool sweeps that model's own parameter: fe for SIDRA Standard US, cf for HCM 2010 and HCM 6.
```
python run_calibration.py --model sidra_standard_us   # fe, 0.5-2.0 (default)
python run_calibration.py --model hcm6                # cf, 0.7-1.3
python run_calibration.py --model hcm2010             # cf, 0.7-1.3
```
`--param cf` still works and selects HCM 6.

Use a different synthetic volume level. This only affects sites with no census match:
```
python run_calibration.py --scenario low      # AADT 5,000/day
python run_calibration.py --scenario medium   # AADT 12,000/day (default)
python run_calibration.py --scenario high     # AADT 25,000/day
```

Change the number of sweep steps:
```
python run_calibration.py --steps 32
```

### Calibration with observed field data

Observed capacity belongs to a particular site, so give it per site in a CSV file (see `examples/observed_capacity_example.csv`):

```
site_id,capacity_veh_h,leg
D03-PLA-89-28,1050,S
D03-PLA-89-28,980,N
D01-DN-199-6,1120,
```

`leg` is the compass approach (S, E, N, W, SE, NE, NW, SW) whose entry lanes you observed. If you give a leg, the tool compares your value with the modeled capacity of that approach's entry lanes. If you leave it blank, the tool uses the average over all entry lanes. Several rows for the same site are averaged.

```
python run_calibration.py --model hcm6 --observed my_capacity.csv --site-id D03-PLA-89-28
```

For each site, bisection finds the parameter value at which SIDRA reproduces the observed capacity. That value goes into the Excel output, and the site's `.sipx` is saved with it. The older `--observed-capacity X` option is still there. It applies one value to every selected site, so use it only if that is what you actually mean.

### Observed turning counts

For calibration, demand should come from counts taken during the same survey as the capacity observations, not from AADT. Give them per site (see `examples/turning_counts_example.csv`):

```
site_id,from_leg,to_leg,lv,hv
D01-DN-199-6,S,N,190,12
D01-DN-199-6,S,E,85,4
...
```

```
python run_calibration.py --counts my_counts.csv --observed my_capacity.csv
```

Counts replace the generated volumes for that site. The leg labels have to match the site's approaches as listed in the Geometry table of `site_results.xlsx`.

### Command-line options summary

| Option | Default | Description |
|---|---|---|
| `--sites N` | all | Process only the first N sites |
| `--site-id ID` | all | Process only this site (repeatable) |
| `--model` | sidra_standard_us | `sidra_standard_us`, `hcm2010` or `hcm6` |
| `--param` | (from model) | Compatibility option: `fe` selects SIDRA Standard US, `cf` selects HCM 6 |
| `--steps N` | 16 | Number of steps in the sensitivity sweep |
| `--observed FILE` | none | Observed capacity per site (CSV) |
| `--observed-capacity X` | none | One observed capacity for all selected sites (veh/h) |
| `--counts FILE` | none | Observed turning counts per site (CSV) |
| `--aadt-file FILE` | data/aadt/ca_route_aadt.csv | Caltrans Traffic Census file (CSV or XLSX) |
| `--k-factor` | 0.09 | Peak hour / AADT, used only when the census has no peak-hour volume |
| `--d-factor` | 0.55 | Peak-direction share of the two-way peak hour |
| `--hv-pct` | 0.06 | Heavy vehicle share |
| `--cross-ratio` | 0.5 | Cross-road volume as a share of route 1 when the cross road has no census data |
| `--geometry` | cache | `cache` (shipped OSM data, no network), `live` (download from OSM) or `defaults` |
| `--scenario` | medium | Synthetic volume level when a site has no census match |

K, D, the heavy vehicle share and the cross-road ratio are planning defaults. We have not validated them for California roundabouts. Set them for each run to fit the district, facility type and setting, or use observed counts instead.

---

## Part 3: Adding AADT Data

Without census data the tool falls back to synthetic volumes. For screening runs with real volumes, add the Caltrans Traffic Census file.

### Step 1: Download the census file

1. Go to https://dot.ca.gov/programs/traffic-operations/census
2. Download the Traffic Volumes (AADT) file
3. Leave it as it is. The tool reads the published layout directly (DISTRICT, RTE, RTE_SFX, CNTY, PM_PFX, PM, PM_SFX, DESCRIPTION, BACK_PEAK_HOUR, BACK_AADT, AHEAD_PEAK_HOUR, AHEAD_AADT and the rest), as CSV or XLSX, with or without title rows above the header. In a workbook, the tool uses the first sheet that has the census header, so the "Preface" sheet at the front of the published file is skipped

### Step 2: Place the file

Save it as `data\aadt\ca_route_aadt.csv` (or `ca_route_aadt.xlsx`), or give its location with `--aadt-file`.

### Step 3: Re-run

```
python run_calibration.py
```

### How sites are matched to the census

- California postmiles restart at each county line, so a site is matched on route and county. The district is used only when the county is missing. Business and other suffixed routes (RTE_SFX) are skipped unless the site's route carries the same suffix.
- The census lists count locations, with volumes BACK of (before) and AHEAD of (after) each postmile. The tool takes the nearest count location. If that location is at or before the site postmile, it uses the AHEAD volume; if it is at or after, the BACK volume. Two equally close locations are averaged. Locations more than 5 postmiles away are ignored.
- When the census gives a peak-hour volume, the tool uses it directly as the two-way peak hour. Otherwise it uses AADT x K.
- Each approach of a route gets the peak-direction volume (two-way peak hour x D). A cross road with no census data is assumed to carry `--cross-ratio` (default 50%) of route 1. This is a planning placeholder. It has not been checked against California counts.
- Postmile prefixes (R, M and so on) are not compared.
- Interchange (ramp terminal) sites are handled differently. There, route 1 is the freeway, and its census volume is mainline traffic that never passes through the roundabout. The tool does not use it. If the crossing road is a state route with census data (route 2 in the site list), that volume is used for the through approaches and the ramp legs get the `--cross-ratio` share. Otherwise the site falls back to synthetic volumes, and the volume note says so. Interchange sites really need counts.

We checked the matching against the 2024 Traffic Volumes file: 55 of the 58 open sites matched, most within 0.3 postmiles of a count location.

The older segment layout (`district, route, pm_start, pm_end, aadt`) still works. A segment that contains the site postmile takes priority.

In the Excel output, the volume source (`caltrans_census`, `synthetic` or `observed_counts`), the AADT and peak hour used for each route, and the total modeled entry demand each have their own column.

---

## Part 4: Understanding the Output

The tool writes two Excel files to the `output/` folder.

### site_results.xlsx

There is one worksheet per site, with these sections.

Site Information lists the ID, district, county, route(s), location, coordinates and lane configuration. It also gives the capacity model, the parameter value the `.sipx` was saved at, the volume source, the census route used, AADT for the main road and for the cross-road or ramp approaches (marked "assumed" when estimated from the main road), the two-way peak hour, the peak-hour basis and the total modeled entry demand (veh/h).

Geometry is a leg-by-leg table: approach (S, E, N, W ...), entry lanes, exit lanes, circulating lanes, circulating width (ft), island diameter (ft), data source and entry demand (veh/h).

Sensitivity Analysis is the main results table, one row per value of the swept parameter (fe for SIDRA Standard US, cf for the HCM models):

| Column | Description |
|---|---|
| Environment Factor (fe) | The parameter value (0.5 to 2.0) |
| Avg Capacity (veh/h) | Mean entry capacity across all approach lanes |
| Min Capacity | Minimum across lanes |
| Max Capacity | Maximum across lanes |
| Avg Deg. Satn (v/c) | Mean degree of saturation |
| Avg Delay (s/veh) | Mean control delay per vehicle |

Each sheet also has a line chart of capacity against the parameter.

Lane Outputs gives per-lane results at the model's default parameter (fe = 1.05 or cf = 1.0):

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

One sheet, one row per site:

| Column | Description |
|---|---|
| Capacity Model | Model used for the run |
| Volume Source | `caltrans_census`, `synthetic` or `observed_counts` |
| AADT Main Road / Cross or Ramps | Daily volumes used for the through approaches and for the cross-road or ramp approaches ("assumed" when estimated from the main road). At interchanges the main road is the crossing route, not the freeway |
| Two-Way Peak Hour Main Road | Peak-hour volume used for the main road (veh/h) |
| Modeled Entry Demand | Sum of all modeled turning movements (veh/h) |
| Cap. @ default | Entry capacity at the default parameter (fe = 1.05 or cf = 1.0) |
| Cap. @ default -0.1 / +0.1 | Capacity 0.1 below and above the default |
| Ctrl Delay @ default | Control delay at the default |
| LOS @ default | Level of Service at the default |
| Calibrated fe / cf | Bisection result when observed capacity was supplied |

---

## Part 5: Calibration Guidance

### Recommended default (no field data)

Use fe = 1.05 for all California SHS roundabouts. This is the SIDRA Standard US HCM default for single-lane roundabouts and produces results consistent with HCM 6th Edition guidance.

### When to adjust fe

| Condition | Recommended fe |
|---|---|
| Default (no site-specific data) | 1.05 |
| Urban site, high pedestrian activity, restricted geometry | 1.2–1.3 |
| Rural site, good sight distance, simple geometry | 0.9–1.0 |
| High heavy vehicle percentage (>10%) | Increase by 0.1–0.2 |

Treat these adjustments as engineering judgment, not as calibrated California values. No near-saturation field data were available during the project, so none of them has been checked against observed capacity. They are reasonable starting points for a sensitivity run. For a design decision, calibrate to field data instead. This table matches Section 4.7 of the final report, and like the report we would not go outside fe = 0.9–1.3 without field data to support it.

### Calibration with field data

When you have field-measured entry capacity (entry flow measured while the approach has a sustained queue):

1. Put each site's observed capacity in a CSV file, with the observed approach (Part 2)
2. Add the turning counts from the same survey (`--counts`)
3. Run: `python run_calibration.py --model [model] --observed [file] --counts [file]`
4. The tool reports the calibrated fe or cf for each site
5. A calibrated fe outside 0.8-1.5 (or cf outside 0.7-1.3) usually means something is wrong with the field data or the geometry. Check both before you use the value

If you measured critical headway (tc) and follow-up headway (tf) rather than capacity, you do not need this tool for HCM 6. Enter A = 3600/tf and B = (tc - tf/2)/3600 directly as the HCM 6 capacity parameters in SIDRA, and leave cf at 1.0 so the calibration is not applied twice. Keep in mind that capacity computed from tc and tf is a model estimate. The tool calibrates against a direct capacity measurement.

Bisection usually gets within ±0.5% of the target capacity in 10–15 SIDRA runs.

### Geometry accuracy

Geometry inputs (inscribed diameter, circulating width, entry angle) move estimated capacity more than fe does. Before you rely on calibrated fe values:

1. Check the inscribed diameter against aerial imagery or design plans
2. Confirm the number of entry and circulating lanes
3. Update `data/sites.csv` if the geometry differs much from the defaults

OSM geometry is fine for screening. Geometry is never a calibration parameter, though, and for calibration it has to match as-built plans or field measurements.

### Units

Inputs are in metres (geometry from OSM or defaults, and `icd_m` in the YAML files). Sites built by the tool use US HCM (Customary), so the tool converts lengths to feet before writing them. It also converts the inscribed diameter to SIDRA's central island diameter (ICD minus two circulating widths). That is why SIDRA and the Excel geometry table show feet.

---

## Part 6: Running Tests

The test suite checks the tool's core logic. Run it before you send results to Caltrans:

```
cd C:\SIDRACalibration
python -m pytest tests/ -v
```

You should get 82 passed (tests for the calibration engine, geometry, volumes, census matching and site loading). The tests do not need SIDRA.

---

## Part 7: Troubleshooting

### "SIDRA API not available"

The tool cannot find the SIDRA v10 DLL. Check that:
- SIDRA Intersection v10 is installed (not v9.1)
- You are running on Windows
- The SIDRA API DLL is registered (re-run the SIDRA installer if needed)

### "OSM geometry not found"

With the default `--geometry cache`, the tool reads the OSM data shipped in `osm/parsed.json` and does not touch the network. A site missing from the cache gets design defaults, and the Geometry note in the output says so.

With `--geometry live`, this message means the tool could not find a roundabout in OpenStreetMap at the site coordinates. Check that:
- The site coordinates in `data/sites.csv` are correct
- The roundabout is mapped in OSM (look it up at https://www.openstreetmap.org)
- Your internet connection works

If OSM fails, the tool falls back to default geometry values.

### SSL certificate verification error (live OSM on an agency network)

Networks that inspect encrypted traffic swap the server certificate for the agency's own, and Python rejects it. Either stay with the default `--geometry cache`, or ask your IT group for the agency root certificate and point Python to a bundle that includes it:
```
set REQUESTS_CA_BUNDLE=C:\certs\agency_ca_bundle.pem
python run_calibration.py --geometry live
```
Please do not switch certificate verification off.

### "SIDRA US template not found"

Every site is built from `templates/us_roundabout_template.sipx`. Restore the `templates/` folder from the repository. The tool stops here on purpose, instead of quietly falling back to SIDRA's generic metric model.

### "The process cannot access the file ... because it is being used by another process"

A sync client (Dropbox, OneDrive) or an open SIDRA window is holding the `.sipx` file. The tool retries for about 10 seconds. If the error persists, close the file in SIDRA or run the tool from a folder that is not synced.

### "SIDRA processing failed: Error #271"

Lane disciplines were not assigned correctly. This is an internal API issue. Contact the project team at akurzhan@berkeley.edu.

### "Error #304: Flow proportions do not add up to 100%"

This can happen after legs are added or removed by hand. Re-run the pipeline from scratch for that site.

### Large output files

Each `.sipx` SIDRA project file is about 60 KB, so the `sites/` folder stays small even for all 58 sites. Git ignores these files (see `.gitignore`), and you do not need to back them up because each run regenerates them. Each file is saved at the calibrated parameter value, or at the model default when no observed capacity was given.

---

## Part 8: Updating the Site List

The site inventory lives in `data/sites.csv`. When Caltrans opens new roundabouts on the SHS:

1. Open `data/sites.csv` in Excel
2. Add a row in the existing format (column headers are in rows 4–5)
3. Set the `Status` column to the year the roundabout opened (for example `2026`)
4. Enter the latitude and longitude from Google Maps or Caltrans GIS
5. Save as CSV (UTF-8)
6. Re-run the pipeline

The next run picks up the new sites automatically.

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
| Model Calibration Factor (cf) | HCM 2010, HCM 6th Edition | 0.7–1.3 | 1.0 | Higher cf = lower capacity |

The two parameters work differently. fe is behavioral: it scales critical gap (tc) and follow-up headway (tf) together. cf is an empirical multiplier on the HCM regression capacity and has no behavioral meaning. Neither should be set outside 0.8–1.5 without field data to back it up.

---

## Appendix C: Contacts

| Role | Name | Email |
|---|---|---|
| Principal Investigator | Alexander Skabardonis | -- |
| Co-PI | Alexander Kurzhanskiy |akurzhan@berkeley.edu |
| Repository | github.com/ucbtrans/sidra-calibration | — |
