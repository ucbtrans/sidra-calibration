"""
run_hcm6_sweep.py  —  TODO item A2
HCM6 calibration factor (cf) sweep via template roundabout.

Uses the 'Roundabout Example US' site already in HCM6 mode inside
template_hcm6.sipx. Sets balanced volumes to representative Qc levels,
sweeps cf 0.7 → 1.3, records capacity.

Outputs (written to sidra-calibration/output/):
  hcm6_sweep_results.json    — raw results
  ../../Task 4/Figure7_HCM6vsStandard.png  — comparison figure

Run from the sidra-calibration/ directory:
    python run_hcm6_sweep.py
"""
import sys, json, shutil, math
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
ROOT     = Path(__file__).parent.parent
TEMPLATE = ROOT / "template_hcm6.sipx"
OUT_DIR  = Path(__file__).parent / "output"
FIG_DIR  = ROOT / "Task 4"
FIG_DATA = FIG_DIR / "figure_data.json"

OUT_DIR.mkdir(exist_ok=True)

# ── CF sweep parameters ──────────────────────────────────────────────────────
CF_VALUES = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
# Volume scenarios: low/medium/high Qc by controlling entry volumes
# Each scenario: (label, lv_per_movement) where LV is light vehicles
# Qc ≈ 0.75 × total_entry × (3 movements per leg / 3 other legs) ≈ lv_per_movement
VOLUME_SCENARIOS = [
    ("Qc~50",  30),   # ~50 veh/h circulating
    ("Qc~200", 120),  # ~200 veh/h circulating
    ("Qc~350", 200),  # ~350 veh/h circulating
]

# ── HCM6 legs in template (orientations: 0=S, 2=E, 3=NE, 6=W) ─────────────
HCM6_LEGS = [0, 2, 3, 6]

def set_balanced_volumes(sid, site, lv_per_movement: int):
    """Set balanced through movements on all leg pairs."""
    hv_per_movement = max(1, round(lv_per_movement * 0.06))
    for orig in HCM6_LEGS:
        for dest in HCM6_LEGS:
            if orig == dest:
                continue
            try:
                sid.set_volume(site, orig, dest,
                               lv_per_movement, hv_per_movement)
            except Exception:
                pass

def get_hcm6_site(sid):
    """Return the HCM6 roundabout site from the open project."""
    proj = sid._project
    for fi in range(proj.SiteFolders.Count):
        folder = proj.SiteFolders[fi]
        for si in range(folder.Sites.Count):
            site = folder.Sites[si]
            if sid.is_hcm6_mode(site) and "Roundabout" in site.Name:
                return site
    raise RuntimeError("HCM6 roundabout site not found in template.")

def run_cf_sweep(lv_per_movement: int, scenario_idx: int):
    """Run cf sweep at a given volume level. Returns list of (cf, mean_cap, caps)."""
    import time
    from sidra_api import SIDRASession

    # Use a unique temp file per scenario to avoid file-lock conflicts
    work_path = str(OUT_DIR / f"work_hcm6_{scenario_idx}.sipx")
    shutil.copy2(str(TEMPLATE), work_path)

    results = []
    with SIDRASession() as sid:
        sid.open_project(work_path)
        site = get_hcm6_site(sid)

        # Set volumes
        set_balanced_volumes(sid, site, lv_per_movement)

        for cf in CF_VALUES:
            sid.set_hcm_calibration_factor(site, cf)
            try:
                sid.process_site(site)
                outputs = sid.read_lane_outputs(site)
                caps = [o["capacity_veh_h"] for o in outputs
                        if o.get("capacity_veh_h", 0) > 0]
                mean_cap = round(np.mean(caps)) if caps else 0
            except Exception as e:
                print(f"    WARNING cf={cf}: {e}")
                caps, mean_cap = [], 0

            results.append({
                "cf": cf,
                "mean_cap": mean_cap,
                "caps": caps,
            })
            print(f"    cf={cf:.1f}  mean_cap={mean_cap:,} veh/h  ({len(caps)} lanes)")

    return results


# ── Main ────────────────────────────────────────────────────────────────────
print("=" * 55)
print("A2: HCM6 calibration factor sweep")
print(f"Template: {TEMPLATE}")
print("=" * 55)

all_results = {}
import gc, time
for idx, (label, lv) in enumerate(VOLUME_SCENARIOS):
    print(f"\n-- Scenario {label} (lv_per_movement={lv}) --")
    all_results[label] = run_cf_sweep(lv, idx)
    gc.collect()
    time.sleep(3)  # let SIDRA COM server release file lock

# Save raw results
out_json = OUT_DIR / "hcm6_sweep_results.json"
with open(out_json, "w") as f:
    json.dump(all_results, f, indent=2)
print(f"\nResults saved: {out_json}")

# ── Figure 7 ────────────────────────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BLUE   = "#1F4E79"
LBLUE  = "#2E75B6"
GREY   = "#595959"
LGREY  = "#D9D9D9"
GREEN  = "#375623"
ORANGE = "#C55A11"
AMBER  = "#D48B00"
DPI    = 300

plt.rcParams.update({
    "font.family": "Arial", "font.size": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.labelcolor": GREY, "xtick.color": GREY, "ytick.color": GREY,
})

std_data   = json.loads(FIG_DATA.read_text())["sweep"]
fe_vals    = sorted(float(k) for k in std_data)
std_means  = [np.mean(std_data[str(fe)]["caps"]) for fe in fe_vals]
std_p10    = [np.percentile(std_data[str(fe)]["caps"], 10) for fe in fe_vals]
std_p90    = [np.percentile(std_data[str(fe)]["caps"], 90) for fe in fe_vals]

fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
fig.patch.set_facecolor("white")

# ── Panel A: absolute capacity curves ────────────────────────────────────
ax = axes[0]

# SIDRA Standard band (clipped to 0.7–1.3 range to match cf)
fe_clip  = [fe for fe in fe_vals if 0.7 <= fe <= 1.3]
std_clip = [np.mean(std_data[str(fe)]["caps"]) for fe in fe_clip]
p10_clip = [np.percentile(std_data[str(fe)]["caps"], 10) for fe in fe_clip]
p90_clip = [np.percentile(std_data[str(fe)]["caps"], 90) for fe in fe_clip]

ax.fill_between(fe_clip, p10_clip, p90_clip,
                color=BLUE, alpha=0.12, label="SIDRA Std. 10–90th pctile")
ax.plot(fe_clip, std_clip, "-o", color=BLUE, lw=1.8, ms=4,
        label="SIDRA Standard (mean, 58 sites)")

# HCM6 scenarios
scenario_colors = [LBLUE, AMBER, ORANGE]
scenario_styles = ["--s", "--^", "--D"]
for (label, _), col, sty in zip(VOLUME_SCENARIOS, scenario_colors, scenario_styles):
    caps = [r["mean_cap"] for r in all_results[label]]
    ax.plot(CF_VALUES, caps, sty, color=col, lw=1.6, ms=4,
            label=f"HCM6 {label}")

ymax = ax.get_ylim()[1] if ax.get_ylim()[1] else 2800
ax.axvline(1.0,  color=ORANGE, lw=0.9, ls=":", alpha=0.7)
ax.text(0.97, ymax * 0.99, "cf=1.0\n(HCM6)", fontsize=6.5,
        color=ORANGE, va="top", ha="right")
ax.axvline(1.05, color=BLUE,   lw=0.9, ls=":", alpha=0.7)
ax.text(1.07, ymax * 0.99, "fe=1.05\n(Std.)", fontsize=6.5,
        color=BLUE, va="top")
ax.set_xlabel("Calibration parameter (fe or cf)", fontsize=9)
ax.set_ylabel("Entry Capacity (veh/h)", fontsize=9)
ax.set_title("SIDRA Standard (fe) vs. HCM6 (cf)\nAbsolute capacity",
             fontsize=9, fontweight="bold", color=BLUE)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x):,}"))
ax.legend(fontsize=7.5, framealpha=0.85)
ax.grid(True, axis="y", color=LGREY, lw=0.4)

# ── Panel B: normalized capacity (relative to default) ───────────────────
ax2 = axes[1]

# SIDRA Standard normalised to fe=1.05
std_default = float(np.interp(1.05, fe_clip, std_clip))
std_norm    = [c / std_default * 100 for c in std_clip]
p10_norm    = [c / std_default * 100 for c in p10_clip]
p90_norm    = [c / std_default * 100 for c in p90_clip]

ax2.fill_between(fe_clip, p10_norm, p90_norm,
                 color=BLUE, alpha=0.12)
ax2.plot(fe_clip, std_norm, "-o", color=BLUE, lw=1.8, ms=4,
         label="SIDRA Standard (mean)")

# HCM6 normalised to cf=1.0
for (label, _), col, sty in zip(VOLUME_SCENARIOS, scenario_colors, scenario_styles):
    caps     = [r["mean_cap"] for r in all_results[label]]
    default  = float(np.interp(1.0, CF_VALUES, caps)) or 1.0
    caps_norm = [c / default * 100 for c in caps]
    ax2.plot(CF_VALUES, caps_norm, sty, color=col, lw=1.6, ms=4,
             label=f"HCM6 {label}")

ax2.axhline(100, color=GREY, lw=0.8, ls="--")
ax2.set_xlabel("Calibration parameter (fe or cf)", fontsize=9)
ax2.set_ylabel("Capacity relative to default (%)", fontsize=9)
ax2.set_title("Normalised sensitivity\n(SIDRA Std. default=fe 1.05; HCM6 default=cf 1.0)",
              fontsize=9, fontweight="bold", color=BLUE)
ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))
ax2.legend(fontsize=7.5, framealpha=0.85)
ax2.grid(True, axis="y", color=LGREY, lw=0.4)

fig.suptitle(
    "Figure 7. SIDRA Standard (fe sweep) vs. HCM6 (cf sweep) — "
    "Capacity Sensitivity Comparison",
    fontsize=9, fontweight="bold", color=BLUE, y=1.02,
)
fig.tight_layout()
fig_path = FIG_DIR / "Figure7_HCM6vsStandard.png"
fig.savefig(fig_path, dpi=DPI, bbox_inches="tight")
plt.close(fig)
print(f"Figure 7 saved: {fig_path}")
