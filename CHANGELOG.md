# Changelog

## 1.1.0 (November 2026)

This release responds to the comments Caltrans sent us after testing version 1.0.

### Fixed
- `--param cf` now actually sweeps the HCM calibration factor. In 1.0 it only
  changed the labels; the site stayed on SIDRA Standard and fe was varied.
  The new `--model` option (`sidra_standard_us`, `hcm2010`, `hcm6`) sets the
  capacity model through `ModelSetting.Rou_Capacity_Model` and sweeps that
  model's own parameter (fe 0.5-2.0, cf 0.7-1.3).
- Sites are now cloned from a US HCM (Customary), right-hand-traffic template
  that ships in `templates/`. In 1.0, sites created with `AddSite()` got
  SIDRA's generic "Standard Right" model in metric units, even when a template
  was present. If the template is missing, the tool now stops with an error
  instead of carrying on with the wrong settings.
- Geometry is converted from metres to the site's unit (feet), and the
  inscribed diameter is converted to SIDRA's central island diameter.
  `calibrate_site.py`, `calibrate_grid.py` and `calibrate_ga.py` used to write
  the inscribed diameter in metres straight into the island diameter field,
  which the US template reads in feet.
- Census matching. The Caltrans Traffic Census file is read as published (CSV
  or XLSX). Sites are matched on route and county, because postmiles restart
  at county lines, and the tool uses the AHEAD or BACK volume of the nearest
  count location. For segment files, a segment that contains the site comes
  first. Version 1.0 matched segment midpoints within 2 miles and filtered by
  district only.
- Interchange sites. At ramp terminals, route 1 is the freeway, and 1.0 put
  its mainline volume on the roundabout approaches. The freeway census volume
  is no longer used; the crossing state route is used when it has census
  data, and the site falls back to synthetic volumes otherwise.
- Census workbooks with a "Preface" sheet in front (the published 2024 file)
  are read correctly; the tool looks for the sheet with the census header.
- Approach volumes. At 3-leg and 4-leg at-grade sites, both approaches of a
  route now carry that route's volume. The 1.0 code gave every leg of a 4-leg
  site (main + cross) / 4, which is about 45% less demand than intended.
- Turning movements now add up exactly to the approach volume
  (largest-remainder rounding). Version 1.0 truncated each movement on its own.
- The `.sipx` file is saved at the calibrated value, or at the model default,
  rather than at the last value of the sweep.
- Leg orientations from live OSM go to the nearest compass direction. In 1.0
  they were assigned in bearing order.
- In the default geometry, the island diameter now agrees with the default
  inscribed diameter and circulating width.

### Added
- `--observed FILE` for observed capacity per site, and optionally per approach.
- `--counts FILE` for observed turning counts per site. They replace the
  generated volumes for that site.
- `--site-id` to run specific sites.
- `--k-factor`, `--d-factor`, `--hv-pct`, `--cross-ratio` and `--aadt-file`.
- `--geometry cache|live|defaults`. The default reads the OSM cache in
  `osm/parsed.json`, so no network access is needed.
- Separate report columns for AADT on route 1 and route 2 (marked "assumed"
  when estimated), two-way peak hour, peak-hour basis and modeled entry
  demand. The 1.0 column labelled "AADT" actually held the total modeled
  peak-hour entry demand.
- A short retry when a sync client briefly locks a new `.sipx` file.
- The `SIDRA_PATH` environment variable, already described in the user
  guide, is now honored.
- `examples/` with CSV templates for observed capacity and turning counts.

### Not changed
- We left the report reproduction scripts (`run_three_model_sweep.py`,
  `run_*_allsites.py`, `run_hcm6_*.py`, `make_sample_sipx.py`) exactly as they
  were used for the final report.
