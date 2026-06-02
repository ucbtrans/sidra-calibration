"""
generate_figure7.py  —  Three-model US capacity sensitivity figure.

All data from model_sweep_summary.json — US RHD only, no NSW/NZ.

Models:
  SIDRA Standard US   (fe,  code=0)
  HCM 2010            (cf,  code=1)
  HCM 6               (cf,  code=2)

Panel A: Absolute capacity bands (P10–Mean–P90) across 47 California SHS sites
Panel B: Normalised sensitivity (each model normalised to its own default=1.0)

Run from sidra-calibration/:
    python generate_figure7.py
"""
import json, sys
import numpy as np
from pathlib import Path

ROOT        = Path(__file__).parent.parent
SWEEP_SUM   = Path(__file__).parent / "output" / "model_sweep_summary.json"
FIG_OUT     = ROOT / "Task 4" / "Figure7_ThreeModelCapacity.png"

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Colour palette ────────────────────────────────────────────────────────────
C_STD  = "#1F4E79"   # dark blue  — SIDRA Standard US
C_HCM2 = "#C55A11"   # burnt orange — HCM 2010
C_HCM6 = "#375623"   # dark green — HCM 6
GREY   = "#595959"
LGREY  = "#D9D9D9"
DPI    = 300

plt.rcParams.update({
    "font.family":        "Arial",
    "font.size":          9,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.labelcolor":    GREY,
    "xtick.color":        GREY,
    "ytick.color":        GREY,
})

# ── Load data ─────────────────────────────────────────────────────────────────
summary = json.loads(SWEEP_SUM.read_text())
cf_vals = summary["cf_values"]          # [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
models  = summary["models"]
sites   = summary["sites"]

def build_matrix(model_key):
    """Return (n_sites × n_cf) numpy array of mean_cap values."""
    rows = []
    for sid, rec in sites[model_key].items():
        sweep = sorted(rec["sweep"], key=lambda x: x["cf"])
        caps  = [r["mean_cap"] for r in sweep]
        if len(caps) == len(cf_vals):
            rows.append(caps)
    mat = np.array(rows, dtype=float)
    return mat

mat_std  = build_matrix("sidra_standard_us")
mat_hcm2 = build_matrix("hcm2010")
mat_hcm6 = build_matrix("hcm6")

n = mat_std.shape[0]
cf1 = cf_vals.index(1.0)

def stats(mat):
    return (np.mean(mat, axis=0),
            np.percentile(mat, 10, axis=0),
            np.percentile(mat, 90, axis=0))

mean_s, p10_s, p90_s = stats(mat_std)
mean_2, p10_2, p90_2 = stats(mat_hcm2)
mean_6, p10_6, p90_6 = stats(mat_hcm6)

print(f"Sites in sweep: {n}")
for label, mean, p10, p90 in [
    ("SIDRA Std (fe=1.0)", mean_s, p10_s, p90_s),
    ("HCM 2010 (cf=1.0)", mean_2, p10_2, p90_2),
    ("HCM 6    (cf=1.0)", mean_6, p10_6, p90_6),
]:
    print(f"  {label}: mean={mean[cf1]:.0f}  P10={p10[cf1]:.0f}  P90={p90[cf1]:.0f} veh/h")

# ── Figure ────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
fig.patch.set_facecolor("white")

def draw_band(ax, xs, mean, p10, p90, color, marker, label_mean, label_band):
    ax.fill_between(xs, p10, p90, color=color, alpha=0.13, label=label_band)
    ax.plot(xs, mean, f"-{marker}", color=color, lw=2, ms=4.5, label=label_mean)

# ── Panel A: Absolute capacity ────────────────────────────────────────────────
ax = axes[0]
draw_band(ax, cf_vals, mean_s, p10_s, p90_s, C_STD,  "o",
          "SIDRA Standard US (mean)", "SIDRA Std P10–P90")
draw_band(ax, cf_vals, mean_2, p10_2, p90_2, C_HCM2, "s",
          "HCM 2010 (mean)", "HCM 2010 P10–P90")
draw_band(ax, cf_vals, mean_6, p10_6, p90_6, C_HCM6, "^",
          "HCM 6 (mean)", "HCM 6 P10–P90")

ax.axvline(1.0, color=GREY, lw=0.8, ls="--", alpha=0.7)
ax.text(1.005, ax.get_ylim()[1] * 0.98, "default\n(param=1.0)",
        fontsize=6.5, color=GREY, va="top")
ax.set_ylim(bottom=0)
ax.set_xlabel("Calibration parameter value (fe or cf)", fontsize=9)
ax.set_ylabel("Mean entry capacity (veh/h per site)", fontsize=9)
ax.set_title(
    "A. Absolute capacity — three US models\n"
    f"California SHS roundabouts ({n} OSM-validated sites)",
    fontsize=9, fontweight="bold", color=GREY)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x):,}"))
ax.legend(fontsize=7.5, framealpha=0.9, ncol=1)
ax.grid(True, axis="y", color=LGREY, lw=0.4)

# ── Panel B: Normalised sensitivity ───────────────────────────────────────────
ax2 = axes[1]

def normalise(mat, cf1_idx):
    return mat / mat[:, cf1_idx:cf1_idx+1] * 100

norm_s = normalise(mat_std,  cf1)
norm_2 = normalise(mat_hcm2, cf1)
norm_6 = normalise(mat_hcm6, cf1)

ms, p10ns, p90ns = stats(norm_s)
m2, p10n2, p90n2 = stats(norm_2)
m6, p10n6, p90n6 = stats(norm_6)

draw_band(ax2, cf_vals, ms, p10ns, p90ns, C_STD,  "o",
          "SIDRA Standard US", "")
draw_band(ax2, cf_vals, m2, p10n2, p90n2, C_HCM2, "s",
          "HCM 2010", "")
draw_band(ax2, cf_vals, m6, p10n6, p90n6, C_HCM6, "^",
          "HCM 6", "")

ax2.axhline(100, color=GREY, lw=0.8, ls="--", alpha=0.6)
ax2.axvline(1.0, color=GREY, lw=0.8, ls="--", alpha=0.7)

sens_s = (mean_s[cf_vals.index(1.1)] - mean_s[cf1]) / mean_s[cf1] * 100
sens_2 = (mean_2[cf_vals.index(1.1)] - mean_2[cf1]) / mean_2[cf1] * 100
sens_6 = (mean_6[cf_vals.index(1.1)] - mean_6[cf1]) / mean_6[cf1] * 100
print(f"\nSensitivity (+0.1 unit): Std={sens_s:+.1f}%  HCM2010={sens_2:+.1f}%  HCM6={sens_6:+.1f}%")

ax2.set_xlabel("Calibration parameter value (fe or cf)", fontsize=9)
ax2.set_ylabel("Capacity relative to param=1.0 default (%)", fontsize=9)
ax2.set_title(
    "B. Normalised sensitivity\n(each model normalised to its own param=1.0 baseline)",
    fontsize=9, fontweight="bold", color=GREY)
ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))
ax2.legend(fontsize=7.5, framealpha=0.9)
ax2.grid(True, axis="y", color=LGREY, lw=0.4)

# ── Suptitle + save ───────────────────────────────────────────────────────────
fig.suptitle(
    "Figure 7.  Entry Capacity Sensitivity — SIDRA Standard US, HCM 2010, HCM 6\n"
    "US Operating Environment, Right-Hand Drive — California SHS Roundabouts",
    fontsize=9.5, fontweight="bold", color="#1F4E79", y=1.02,
)
fig.tight_layout()
fig.savefig(FIG_OUT, dpi=DPI, bbox_inches="tight")
plt.close(fig)
print(f"\nFigure 7 saved: {FIG_OUT}")
