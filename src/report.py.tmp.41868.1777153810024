"""
report.py
Generate Excel output reports for SIDRA calibration results.

Produces two workbooks:

1. site_results.xlsx  – one sheet per site with:
   - Site metadata (location, geometry)
   - Input volumes by leg
   - Sensitivity sweep table (parameter vs. capacity/delay/v/c)
   - Calibration result (if observed data available)
   - Charts: capacity vs. Environment Factor

2. summary.xlsx – cross-site summary table:
   - All sites, key metrics at default and calibrated parameters
   - Suitable for inclusion in the Task 4 working paper

Requires:  pip install openpyxl
"""

from __future__ import annotations
import math
from pathlib import Path
from typing import Optional

try:
    import openpyxl
    from openpyxl import Workbook
    from openpyxl.styles import (Font, PatternFill, Alignment, Border, Side,
                                 numbers)
    from openpyxl.chart import LineChart, Reference
    from openpyxl.chart.series import SeriesLabel
    from openpyxl.utils import get_column_letter
    _OPENPYXL_AVAILABLE = True
except ImportError:
    _OPENPYXL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Colour palette (Caltrans/PATH report style)
# ---------------------------------------------------------------------------
COL_HEADER_BG  = "1F4E79"   # dark blue
COL_HEADER_FG  = "FFFFFF"   # white
COL_SUBHDR_BG  = "BDD7EE"   # light blue
COL_ALT_ROW    = "EEF4FB"   # very light blue
COL_GOOD       = "C6EFCE"   # green (within target)
COL_WARN       = "FFEB9C"   # yellow
COL_BAD        = "FFC7CE"   # red


def _require_openpyxl():
    if not _OPENPYXL_AVAILABLE:
        raise ImportError("openpyxl required: pip install openpyxl")


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------
def _header_style(ws, row: int, col: int, value, bold: bool = True,
                  bg: str = COL_HEADER_BG, fg: str = COL_HEADER_FG,
                  wrap: bool = False):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font      = Font(bold=bold, color=fg, size=10)
    cell.fill      = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(horizontal="center", vertical="center",
                               wrap_text=wrap)
    return cell


def _thin_border():
    thin = Side(style="thin")
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def _set_col_width(ws, col: int, width: float):
    ws.column_dimensions[get_column_letter(col)].width = width


# ---------------------------------------------------------------------------
# Site report
# ---------------------------------------------------------------------------
def write_site_report(output_path: str,
                      sites_data: list[dict]) -> None:
    """
    Write a multi-sheet Excel workbook, one sheet per site.

    Each element of sites_data is a dict with keys:
      site_id      : str
      site_name    : str
      lat, lon     : float
      n_legs       : int
      lane_config  : str
      district     : int
      county       : str
      route1       : str
      aadt1        : int
      aadt_source  : str
      geometry     : RoundaboutGeometry (or None)
      turning_movements : TurningMovements (or None)
      sensitivity  : SensitivityResult (or None)
      calibration  : CalibrationResult (or None)
      lane_outputs : list[dict] at default fe
    """
    _require_openpyxl()
    wb = Workbook()
    wb.remove(wb.active)   # remove default sheet

    for sd in sites_data:
        _write_site_sheet(wb, sd)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"Site report saved: {output_path}")


def _write_site_sheet(wb: Workbook, sd: dict):
    sid   = sd.get("site_id", "Site")
    sname = sd.get("site_name", sid)
    ws    = wb.create_sheet(title=_safe_sheet_name(sid))

    row = 1

    # --- Title ---------------------------------------------------------------
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
    title_cell = ws.cell(row=row, column=1,
                         value=f"SIDRA Calibration – {sname}")
    title_cell.font      = Font(bold=True, size=13, color=COL_HEADER_BG)
    title_cell.alignment = Alignment(horizontal="left")
    row += 2

    # --- Site metadata -------------------------------------------------------
    _header_style(ws, row, 1, "Site Information", bg=COL_SUBHDR_BG,
                  fg="000000", bold=True)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    row += 1

    meta = [
        ("Site ID",       sd.get("site_id")),
        ("District",      sd.get("district")),
        ("County",        sd.get("county")),
        ("Route(s)",      sd.get("route1")),
        ("Location",      sd.get("site_name")),
        ("Latitude",      sd.get("lat")),
        ("Longitude",     sd.get("lon")),
        ("# Legs",        sd.get("n_legs")),
        ("Lane Config",   sd.get("lane_config")),
        ("AADT (Route 1)",sd.get("aadt1")),
        ("AADT Source",   sd.get("aadt_source")),
    ]
    for label, value in meta:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True, size=10)
        ws.cell(row=row, column=2, value=value)
        row += 1
    row += 1

    # --- Geometry summary ----------------------------------------------------
    geom = sd.get("geometry")
    if geom and hasattr(geom, "legs") and geom.legs:
        _header_style(ws, row, 1, "Geometry (from OSM / defaults)",
                      bg=COL_SUBHDR_BG, fg="000000", bold=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        row += 1

        headers = ["Leg", "Orientation", "Entry Lanes", "Exit Lanes",
                   "Circ. Lanes", "Circ. Width (m)", "Source"]
        for c, h in enumerate(headers, 1):
            _header_style(ws, row, c, h, bg=COL_HEADER_BG)
        row += 1

        for leg in geom.legs:
            ws.cell(row=row, column=1, value=leg.leg_name)
            ws.cell(row=row, column=2, value=leg.leg_idx)
            ws.cell(row=row, column=3, value=leg.n_entry_lanes)
            ws.cell(row=row, column=4, value=leg.n_exit_lanes)
            ws.cell(row=row, column=5, value=leg.n_circ_lanes)
            ws.cell(row=row, column=6, value=leg.circulating_width_m)
            ws.cell(row=row, column=7, value=leg.source)
            row += 1
        row += 1

    # --- Sensitivity sweep ---------------------------------------------------
    sweep_data = sd.get("sensitivity")
    sweep_start_row = None
    if sweep_data and hasattr(sweep_data, "sweep") and sweep_data.sweep:
        param_label = "Environment Factor (fe)" if sweep_data.parameter == "fe" \
                      else "HCM Calibration Factor"
        _header_style(ws, row, 1, f"Sensitivity Analysis – {param_label}",
                      bg=COL_SUBHDR_BG, fg="000000", bold=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        row += 1

        hdrs = [param_label, "Avg Capacity (veh/h)", "Min Capacity",
                "Max Capacity", "Avg Deg. Satn (v/c)", "Avg Delay (s/veh)"]
        for c, h in enumerate(hdrs, 1):
            _header_style(ws, row, c, h)
        row += 1

        sweep_start_row = row
        for i, pt in enumerate(sweep_data.sweep):
            if "error" in pt:
                ws.cell(row=row, column=1, value=pt["value"])
                ws.cell(row=row, column=2, value=f"Error: {pt['error']}")
            else:
                ws.cell(row=row, column=1, value=pt.get("value"))
                ws.cell(row=row, column=2, value=_fmt(pt.get("capacity_avg")))
                ws.cell(row=row, column=3, value=_fmt(pt.get("capacity_min")))
                ws.cell(row=row, column=4, value=_fmt(pt.get("capacity_max")))
                ws.cell(row=row, column=5, value=_fmt(pt.get("deg_satn_avg"), 3))
                ws.cell(row=row, column=6, value=_fmt(pt.get("avg_delay_avg"), 1))
                # Colour-code v/c column
                ds = pt.get("deg_satn_avg")
                if ds is not None:
                    cell = ws.cell(row=row, column=5)
                    if ds < 0.70:
                        cell.fill = PatternFill("solid", fgColor=COL_GOOD)
                    elif ds < 0.85:
                        cell.fill = PatternFill("solid", fgColor=COL_WARN)
                    else:
                        cell.fill = PatternFill("solid", fgColor=COL_BAD)
            row += 1

        # --- Chart: capacity vs. parameter -----------------------------------
        if sweep_start_row:
            n_rows = row - sweep_start_row
            chart = LineChart()
            chart.title = f"Entry Capacity vs. {param_label}"
            chart.style = 10
            chart.y_axis.title = "Avg Entry Capacity (veh/h)"
            chart.x_axis.title = param_label
            chart.width  = 16
            chart.height = 10

            data_ref = Reference(ws, min_col=2, max_col=2,
                                 min_row=sweep_start_row - 1,
                                 max_row=sweep_start_row + n_rows - 1)
            cats_ref = Reference(ws, min_col=1,
                                 min_row=sweep_start_row,
                                 max_row=sweep_start_row + n_rows - 1)
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats_ref)
            ws.add_chart(chart, f"H{sweep_start_row}")
        row += 1

    # --- Lane outputs at default parameters ----------------------------------
    lane_outs = sd.get("lane_outputs", [])
    if lane_outs:
        _header_style(ws, row, 1, "Lane Outputs (default parameters)",
                      bg=COL_SUBHDR_BG, fg="000000", bold=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        row += 1

        hdrs = ["Leg", "Lane", "Flow (veh/h)", "Capacity (veh/h)",
                "Deg. Satn (v/c)", "Ctrl Delay (s/veh)", "LOS", "95th Queue (veh)"]
        for c, h in enumerate(hdrs, 1):
            _header_style(ws, row, c, h)
        row += 1

        for lo in lane_outs:
            ws.cell(row=row, column=1, value=lo.get("leg_name"))
            ws.cell(row=row, column=2, value=lo.get("lane_no"))
            ws.cell(row=row, column=3, value=_fmt(lo.get("flow_veh_h")))
            ws.cell(row=row, column=4, value=_fmt(lo.get("capacity_veh_h")))
            ds_cell = ws.cell(row=row, column=5, value=_fmt(lo.get("deg_satn"), 3))
            ws.cell(row=row, column=6, value=_fmt(lo.get("avg_delay_s"), 1))
            ws.cell(row=row, column=7, value=lo.get("level_of_service"))
            ws.cell(row=row, column=8, value=_fmt(lo.get("queue_95pct_veh"), 1))
            ds = lo.get("deg_satn")
            if ds is not None:
                if ds < 0.70:   ds_cell.fill = PatternFill("solid", fgColor=COL_GOOD)
                elif ds < 0.85: ds_cell.fill = PatternFill("solid", fgColor=COL_WARN)
                else:           ds_cell.fill = PatternFill("solid", fgColor=COL_BAD)
            row += 1
        row += 1

    # --- Calibration result --------------------------------------------------
    cal = sd.get("calibration")
    if cal:
        _header_style(ws, row, 1, "Calibration Result",
                      bg=COL_SUBHDR_BG, fg="000000", bold=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        row += 1
        cal_items = [
            ("Method",              cal.method),
            ("Parameter",           cal.parameter),
            ("Calibrated value",    cal.value),
            ("Estimated capacity",  cal.capacity_estimated),
            ("Observed capacity",   cal.capacity_observed),
            ("Error (%)",           cal.error_pct),
            ("Converged",           cal.converged),
            ("Iterations",          cal.n_iterations),
            ("Notes",               cal.notes),
        ]
        for label, value in cal_items:
            ws.cell(row=row, column=1, value=label).font = Font(bold=True, size=10)
            ws.cell(row=row, column=2, value=value)
            row += 1

    # Column widths
    for c, w in enumerate([20, 14, 14, 14, 14, 16, 12], 1):
        _set_col_width(ws, c, w)


# ---------------------------------------------------------------------------
# Cross-site summary workbook
# ---------------------------------------------------------------------------
def write_summary_report(output_path: str, sites_data: list[dict]) -> None:
    """
    Write a single-sheet summary comparing all sites.
    """
    _require_openpyxl()
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"

    row = 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=12)
    title = ws.cell(row=row, column=1,
                    value="SIDRA Calibration Study – Site Summary")
    title.font      = Font(bold=True, size=14, color=COL_HEADER_BG)
    title.alignment = Alignment(horizontal="left")
    row += 2

    headers = [
        "Site ID", "District", "County", "Route", "Location",
        "# Legs", "Lane Config", "AADT", "AADT Source",
        "Default Cap. (veh/h)", "Cap. @ fe=0.9", "Cap. @ fe=1.1",
        "Ctrl Delay @ default (s/veh)", "LOS @ default", "Notes",
    ]
    for c, h in enumerate(headers, 1):
        _header_style(ws, row, c, h)
    row += 1

    for sd in sites_data:
        sweep = sd.get("sensitivity")
        cap_default = cap_lo = cap_hi = delay_default = None

        los_default = None
        if sweep and hasattr(sweep, "sweep"):
            for pt in sweep.sweep:
                if "error" in pt:
                    continue
                v = pt.get("value", 0)
                if abs(v - 1.05) < 0.06:   # near default fe
                    cap_default   = pt.get("capacity_avg")
                    delay_default = pt.get("avg_delay_avg")
                if abs(v - 0.90) < 0.06:
                    cap_lo = pt.get("capacity_avg")
                if abs(v - 1.10) < 0.06:
                    cap_hi = pt.get("capacity_avg")

        # LOS from baseline lane outputs
        lane_outs = sd.get("lane_outputs", [])
        if lane_outs:
            los_vals = [lo.get("level_of_service") for lo in lane_outs
                        if lo.get("level_of_service")]
            los_default = los_vals[0] if los_vals else None
            if not delay_default:
                delays = [lo.get("avg_delay_s") for lo in lane_outs
                          if lo.get("avg_delay_s") is not None]
                delay_default = sum(delays) / len(delays) if delays else None

        vals = [
            sd.get("site_id"), sd.get("district"), sd.get("county"),
            sd.get("route1"), sd.get("site_name"),
            sd.get("n_legs"), sd.get("lane_config"),
            sd.get("aadt1"), sd.get("aadt_source"),
            _fmt(cap_default), _fmt(cap_lo), _fmt(cap_hi),
            _fmt(delay_default, 1), los_default,
            sd.get("notes", ""),
        ]
        for c, v in enumerate(vals, 1):
            ws.cell(row=row, column=c, value=v)
        row += 1

    # Column widths
    widths = [12, 8, 10, 8, 30, 7, 12, 10, 14, 14, 14, 14, 18, 30]
    for c, w in enumerate(widths, 1):
        _set_col_width(ws, c, w)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"Summary report saved: {output_path}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_sheet_name(name: str) -> str:
    """Truncate and sanitize an Excel sheet name."""
    bad = r'\/:*?[]'
    for ch in bad:
        name = name.replace(ch, "_")
    return name[:31]


def _fmt(value, decimals: int = 0):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if decimals == 0:
        return int(round(value))
    return round(value, decimals)
