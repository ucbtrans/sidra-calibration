"""
generate_ec_allsites_figure.py - plot the inventory-wide REAL SIDRA
Entry-Circulating Flow Adjustment sweep (output of run_ec_sweep_allsites.py).
"""
import json, sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", line_buffering=True)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DATA = Path(__file__).resolve().parents[1] / "output" / "erratum" / "ec_allsites" / "ec_allsites_summary.json"
OUT  = Path(__file__).resolve().parents[2] / "Task 6" / "Erratum" / "Fig12_ECrealAll_corrected.png"

d = json.loads(DATA.read_text(encoding="utf-8"))
recs = [r for r in d["sites"] if r.get("ok")]
labels = d["ec_labels"]
n = len(recs)

# Per-level gains across sites
gains = {k: np.array([r["gain_pct"][k] for r in recs]) for k in range(4)}
high_gains = gains[3]

GREY, LGREY, BLUE = "#303030", "#D0D0D0", "#1F4E79"
plt.rcParams.update({"font.family": "Arial", "font.size": 9,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.labelcolor": GREY, "xtick.color": GREY, "ytick.color": GREY})

fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
fig.patch.set_facecolor("white")

# Panel A - distribution of High-level gain across sites
ax = axes[0]
ax.hist(high_gains, bins=12, color=BLUE, edgecolor="white")
mean_h = float(np.mean(high_gains))
ax.axvline(mean_h, color="#C55A11", lw=1.6, ls="--",
           label=f"mean = {mean_h:.2f}%")
ax.set_xlabel("Capacity gain at High vs None (%)", fontsize=9)
ax.set_ylabel("Number of sites", fontsize=9)
ax.set_title(f"A. Distribution of High-level gain\n({n} OSM-validated sites, SIDRA Standard US, saturated)",
             fontsize=9, fontweight="bold", color=GREY)
ax.legend(fontsize=8, framealpha=0.9)
ax.grid(True, axis="y", color=LGREY, lw=0.4)

# Panel B - mean gain per EC level with site spread (P10-P90)
ax2 = axes[1]
x = np.arange(4)
means = [float(np.mean(gains[k])) for k in range(4)]
p10 = [float(np.percentile(gains[k], 10)) for k in range(4)]
p90 = [float(np.percentile(gains[k], 90)) for k in range(4)]
yerr = [[means[k]-p10[k] for k in range(4)], [p90[k]-means[k] for k in range(4)]]
ax2.bar(x, means, 0.6, color=BLUE, yerr=yerr, capsize=4,
        error_kw={"ecolor": GREY, "lw": 1})
for xi, m in zip(x, means):
    ax2.text(xi, m, f"+{m:.2f}%", ha="center", va="bottom", fontsize=8.5)
ax2.set_xticks(x); ax2.set_xticklabels(labels)
ax2.set_xlabel("Entry-Circulating Flow Adjustment level", fontsize=9)
ax2.set_ylabel("Mean capacity gain vs None (%)", fontsize=9)
ax2.set_title("B. Mean gain by level across sites\n(whiskers: P10 to P90 site spread)",
              fontsize=9, fontweight="bold", color=GREY)
ax2.grid(True, axis="y", color=LGREY, lw=0.4)

fig.suptitle(
    f"Figure 12 (corrected). Entry-Circulating Flow Adjustment across the inventory - "
    f"real SIDRA v10 ({n} sites, SIDRA Standard US, saturated)",
    fontsize=10, fontweight="bold", color=BLUE, y=1.02)
fig.tight_layout()
fig.savefig(OUT, dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {OUT}")
print(f"n sites: {n}")
print(f"mean gains: {d['mean_gain_pct']}")
print(f"median gains: {d['median_gain_pct']}")
print(f"max gains: {d['max_gain_pct']}")
