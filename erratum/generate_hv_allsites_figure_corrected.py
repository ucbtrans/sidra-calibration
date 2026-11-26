"""
generate_hv_allsites_figure.py - plot the inventory-wide REAL SIDRA heavy
vehicle sweep (output of run_hv_sweep_allsites.py).
"""
import json, sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", line_buffering=True)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DATA = Path(__file__).resolve().parents[1] / "output" / "erratum" / "hv_allsites" / "hv_allsites_summary.json"
OUT  = Path(__file__).resolve().parents[2] / "Task 6" / "Erratum" / "Fig08_HVreal_corrected.png"

d = json.loads(DATA.read_text(encoding="utf-8"))
recs = [r for r in d["sites"] if r.get("ok")]
labels = d["hv_labels"]
nlev = len(labels)
n = len(recs)
xpts = [2, 6, 10, 15, 20]

caps = {k: np.array([r["caps"][k] for r in recs]) for k in range(nlev)}
chg  = {k: np.array([r["chg_pct_vs_6"][k] for r in recs]) for k in range(nlev)}

GREY, LGREY, BLUE, ORNG = "#303030", "#D0D0D0", "#1F4E79", "#C55A11"
plt.rcParams.update({"font.family": "Arial", "font.size": 9,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.labelcolor": GREY, "xtick.color": GREY, "ytick.color": GREY})

fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
fig.patch.set_facecolor("white")

# Panel A - mean capacity vs HV% with P10-P90 band
ax = axes[0]
means = [float(np.mean(caps[k])) for k in range(nlev)]
p10 = [float(np.percentile(caps[k], 10)) for k in range(nlev)]
p90 = [float(np.percentile(caps[k], 90)) for k in range(nlev)]
ax.fill_between(xpts, p10, p90, color=BLUE, alpha=0.15, label="P10 to P90")
ax.plot(xpts, means, "-o", color=BLUE, lw=2.0, ms=5, label="Mean")
ax.axvline(6, color=GREY, lw=0.9, ls="--", alpha=0.7, label="6% baseline")
ax.set_xlabel("Heavy vehicle share (%)", fontsize=9)
ax.set_ylabel("Mean entry capacity (veh/h)", fontsize=9)
ax.set_title(f"A. Entry capacity vs heavy vehicle share\n({n} sites, SIDRA Standard US, fe=1.05, saturated)",
             fontsize=9, fontweight="bold", color=GREY)
ax.legend(fontsize=8, framealpha=0.9)
ax.grid(True, axis="y", color=LGREY, lw=0.4)

# Panel B - % change vs 6% baseline
ax2 = axes[1]
x = np.arange(nlev)
cmeans = [float(np.mean(chg[k])) for k in range(nlev)]
colors = [ORNG if m < 0 else BLUE for m in cmeans]
ax2.bar(x, cmeans, 0.6, color=colors)
for xi, m in zip(x, cmeans):
    ax2.text(xi, m + (0.2 if m >= 0 else -0.2), f"{m:+.1f}%",
             ha="center", va="bottom" if m >= 0 else "top", fontsize=8.5)
ax2.axhline(0, color=GREY, lw=0.8)
ax2.set_xticks(x); ax2.set_xticklabels(labels)
ax2.set_xlabel("Heavy vehicle share", fontsize=9)
ax2.set_ylabel("Mean capacity change vs 6% (%)", fontsize=9)
ax2.set_title("B. Capacity change from 6% baseline\n(mean across sites)",
              fontsize=9, fontweight="bold", color=GREY)
ax2.grid(True, axis="y", color=LGREY, lw=0.4)

fig.suptitle(
    f"Figure 8 (corrected). Heavy vehicle sensitivity across the inventory - "
    f"real SIDRA v10 ({n} sites, SIDRA Standard US, saturated)",
    fontsize=10, fontweight="bold", color=BLUE, y=1.02)
fig.tight_layout()
fig.savefig(OUT, dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {OUT}")
print(f"n sites: {n}")
print(f"mean cap: {d['mean_cap']}")
print(f"mean chg vs 6%: {d['mean_chg_pct_vs_6']}")
