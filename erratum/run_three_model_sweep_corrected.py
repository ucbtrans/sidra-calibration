"""
ERRATUM RE-RUN (November 2026) of run_three_model_sweep.py.

Identical to the original except for two changes:
  1. Island diameter is written as the central island diameter in the
     template's length unit: ICD (m) x 3.28084 - 2 x circulating width (ft).
     The original wrote the inscribed diameter in metres directly.
  2. Outputs go to output/erratum/ (or Task 6/Erratum/) so the published
     results are not overwritten.
"""

import sys, json, shutil, gc, time, io, math
import numpy as np
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT     = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "template_hcm6.sipx"   # US RHD base; model switched programmatically
OSM_FILE = Path(__file__).resolve().parents[1] / "osm" / "parsed.json"
FIG_DATA = ROOT / "Task 4" / "figure_data.json"
OUT_BASE = Path(__file__).resolve().parents[1] / "output" / "erratum" / "model_sweep"
OUT_BASE.mkdir(parents=True, exist_ok=True)

CF_VALUES = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
MIN_ICD   = 16.0   # erratum: smaller OSM ICDs leave no room for a central island (see compare script)

# Group A Akcelik params (volumes back-calculated from the Task 4 screening capacities)
TF_A, TC_STD, QC_A = 2.05, 4.5, 51.0
TF_B                = 2.50

HCM6_LEGS = [0, 2, 3, 6]

# ── Model definitions ────────────────────────────────────────────────────────
MODELS = [
    {"code": 0, "key": "sidra_standard_us", "label": "SIDRA Standard US", "param": "fe"},
    {"code": 1, "key": "hcm2010",           "label": "HCM 2010",          "param": "cf"},
    {"code": 2, "key": "hcm6",              "label": "HCM 6",             "param": "cf"},
]

for m in MODELS:
    (OUT_BASE / m["key"]).mkdir(exist_ok=True)

# ── Load data ─────────────────────────────────────────────────────────────────
osm_data = json.loads(OSM_FILE.read_text())
fig_data = json.loads(FIG_DATA.read_text())
sites    = fig_data["sites"]

# ── Helpers ───────────────────────────────────────────────────────────────────
def back_calc_qc(cap_default):
    if cap_default >= 1640:
        return QC_A
    cmax = 3600.0 / TF_B
    return max(-(3600.0 / TC_STD) * math.log(cap_default / cmax), 1.0)

def lv_for_qc(qc):
    return max(1, round(qc / 2.25))

def get_us_roundabout_site(sid):
    proj = sid._project
    for fi in range(proj.SiteFolders.Count):
        folder = proj.SiteFolders[fi]
        for si in range(folder.Sites.Count):
            s = folder.Sites[si]
            if "Roundabout" in s.Name and not s.Driveonleft:
                return s
    raise RuntimeError("US roundabout site not found in template.")

def set_capacity_model(site, code: int):
    site.ModelSetting.Rou_Capacity_Model = code

def set_calibration_param(sid, site, model_code: int, value: float):
    for leg_idx in range(8):
        leg = sid._get_leg(site, leg_idx)
        if leg is None:
            continue
        rleg = leg.Leg_roundabout
        try:
            if model_code == 0:
                rleg.Environment_factor = value
            elif model_code == 1:
                rleg.LegRouHCM2010.Model_calib_factor = value
            elif model_code == 2:
                rleg.LegRouHCM6.Model_calib_factor = value
        except Exception:
            pass

def set_geometry(sid, site, icd_m, circ_lanes):
    for leg_idx in range(8):
        leg = sid._get_leg(site, leg_idx)
        if leg is None:
            continue
        rleg = leg.Leg_roundabout
        try:
            rleg.Island_diameter = max(1.0, float(icd_m) * 3.28084 - 2.0 * float(rleg.Circulating_width))
            rleg.Num_circulating_lanes = int(circ_lanes)
        except Exception:
            pass

def set_volumes(sid, site, lv):
    hv = max(1, round(lv * 0.06))
    for orig in HCM6_LEGS:
        for dest in HCM6_LEGS:
            if orig != dest:
                try:
                    sid.set_volume(site, orig, dest, lv, hv)
                except Exception:
                    pass

# ── Build usable site list ────────────────────────────────────────────────────
usable = []
for s in sites:
    sid_ = s["site_id"]
    o    = osm_data.get(sid_, {})
    if not o.get("found") or o.get("icd_m") is None or o["icd_m"] < MIN_ICD:
        continue
    nappr = len(o.get("approach_ways", []))
    icd   = o["icd_m"]
    circ  = 2 if (icd > 35 and nappr >= 6) else 1
    qc    = back_calc_qc(s["cap_default"])
    lv    = lv_for_qc(qc)
    usable.append({
        "site_id":    sid_,
        "district":   s["district"],
        "lane_config": s["lane_config"],
        "cap_default": s["cap_default"],
        "icd_m":      icd,
        "circ_lanes": circ,
        "qc":         round(qc, 1),
        "lv":         lv,
    })

print("=" * 65)
print("Three-model sweep — California SHS roundabouts (OSM geometry)")
print(f"Template:     {TEMPLATE}")
print(f"Sites usable: {len(usable)}/58")
print(f"Models:       {', '.join(m['label'] for m in MODELS)}")
print(f"CF values:    {CF_VALUES}")
print("=" * 65)

# ── Main loop: one model at a time, cache per site ────────────────────────────
all_summary = {m["key"]: {} for m in MODELS}

for model in MODELS:
    mcode = model["code"]
    mkey  = model["key"]
    mlabel = model["label"]
    out_dir = OUT_BASE / mkey

    print(f"\n{'='*65}")
    print(f"Model: {mlabel}  (Rou_Capacity_Model={mcode})")
    print(f"{'='*65}")

    for i, s in enumerate(usable):
        site_id  = s["site_id"]
        out_file = out_dir / f"{site_id}.json"

        if out_file.exists():
            print(f"  [{i+1:02d}/{len(usable)}] {site_id}  (cached)")
            all_summary[mkey][site_id] = json.loads(out_file.read_text())
            continue

        print(f"  [{i+1:02d}/{len(usable)}] {site_id}  "
              f"ICD={s['icd_m']}m  circ={s['circ_lanes']}  Qc~{s['qc']:.0f}  lv={s['lv']}")

        _W = Path(__import__("tempfile").gettempdir()) / "sidra_erratum_work"; _W.mkdir(exist_ok=True)
        work = str(_W / f"_work_{mkey}_{site_id}.sipx")  # outside Dropbox (sync locks)
        shutil.copy2(str(TEMPLATE), work)

        sweep = []
        try:
            from sidra_api import SIDRASession
            with SIDRASession() as sid:
                sid.open_project(work)
                site = get_us_roundabout_site(sid)
                set_capacity_model(site, mcode)
                set_geometry(sid, site, s["icd_m"], s["circ_lanes"])
                set_volumes(sid, site, s["lv"])

                for cf in CF_VALUES:
                    set_calibration_param(sid, site, mcode, cf)
                    try:
                        sid.process_site(site)
                        outputs = sid.read_lane_outputs(site)
                        caps = [o["capacity_veh_h"] for o in outputs
                                if o.get("capacity_veh_h", 0) > 0]
                        mean_cap = round(float(np.mean(caps))) if caps else 0
                        delay_vals = [o.get("avg_delay_s", 0) for o in outputs
                                      if o.get("avg_delay_s") is not None]
                        mean_delay = round(float(np.mean(delay_vals)), 1) if delay_vals else None
                    except Exception as e:
                        print(f"      WARNING {model['param']}={cf}: {e}")
                        caps, mean_cap, mean_delay = [], 0, None

                    sweep.append({
                        "cf": cf, "mean_cap": mean_cap,
                        "mean_delay": mean_delay, "caps": caps,
                    })

            caps_at_default = next(
                (r["mean_cap"] for r in sweep if r["cf"] == 1.0), 0)
            print(f"        {model['param']}=1.0 -> {caps_at_default:,} veh/h")

        except Exception as exc:
            print(f"        FAILED: {exc}")
            sweep = []

        try:
            Path(work).unlink()
        except Exception:
            pass

        record = {**s, "model": mlabel, "param": model["param"], "sweep": sweep}
        out_file.write_text(json.dumps(record, indent=2))
        all_summary[mkey][site_id] = record

        gc.collect()
        time.sleep(3)

# ── Save combined summary ─────────────────────────────────────────────────────
summary = {
    "n_sites":   len(usable),
    "cf_values": CF_VALUES,
    "models":    {m["key"]: {"label": m["label"], "param": m["param"], "code": m["code"]}
                  for m in MODELS},
    "sites":     all_summary,
}
summary_path = Path(__file__).resolve().parents[1] / "output" / "erratum" / "model_sweep_summary.json"
summary_path.write_text(json.dumps(summary, indent=2))

print()
print("=" * 65)
total = sum(len(v) for v in all_summary.values())
print(f"Done.  {total} site-model combinations processed.")
print(f"Output: {OUT_BASE}")
print(f"Summary: {summary_path}")
