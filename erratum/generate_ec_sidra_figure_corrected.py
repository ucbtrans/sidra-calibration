"""
generate_ec_sidra_figure.py - plot the REAL SIDRA Entry-Circulating Flow
Adjustment sweep (output of run_ec_sweep_sidra.py) for the final report.
"""
import json, sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", line_buffering=True)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DATA = Path(__file__).resolve().parents[1] / "output" / "erratum" / "ec_sweep_sidra.json"
OUT  = Path(__file__).resolve().parents[2] / "Task 6" / "Erratum" / "Fig11_ECrealSingle_corrected.png"

d = json.loads(DATA.read_text(encoding="utf-8"))
models = d["models"]
labels = ["None", "Low", "Medium", "High"]
x = np.arange(len(labels))

GREY, LGREY = "#303030", "#D0D0D0"
COLORS = {"SIDRA Standard US": "#1F4E79", "HCM 2010": "#C55A11", "HCM 6": "#375623"}

plt.rcParams.update({"font.family": "Arial", "font.size": 9,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.labelcolor": GREY, "xtick.color": GREY, "ytick.color": GREY})

fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
fig.patch.set_facecolor("white")

# Panel A - absolute capacity vs EC level, all three models
ax = axes[0]
for mlabel, md in models.items():
    ax.plot(x, md["caps"], "-o", color=COLORS.get(mlabel, GREY), lw=2.0, ms=5,
            label=mlabel)
ax.set_xticks(x); ax.set_xticklabels(labels)
ax.set_xlabel("Entry-Circulating Flow Adjustment level", fontsize=9)
ax.set_ylabel("Entry capacity (veh/h)", fontsize=9)
ax.set_title("A. Entry capacity vs adjustment level\n(synthetic saturated site, real SIDRA v10 runs)",
             fontsize=9, fontweight="bold", color=GREY)
ax.legend(fontsize=8, framealpha=0.9)
ax.grid(True, axis="y", color=LGREY, lw=0.4)

# Panel B - percent gain vs None
ax2 = axes[1]
width = 0.6
std = models.get("SIDRA Standard US", {})
gains = std.get("gain_pct_vs_None", [0, 0, 0, 0])
bars = ax2.bar(x, gains, width, color="#1F4E79")
for xi, g in zip(x, gains):
    ax2.text(xi, g + 0.05, f"+{g:.2f}%", ha="center", va="bottom", fontsize=8.5)
ax2.set_xticks(x); ax2.set_xticklabels(labels)
ax2.set_xlabel("Entry-Circulating Flow Adjustment level", fontsize=9)
ax2.set_ylabel("Capacity gain vs None (%)", fontsize=9)
ax2.set_title("B. SIDRA Standard US capacity gain\n(HCM 2010 and HCM 6 show no effect)",
              fontsize=9, fontweight="bold", color=GREY)
ax2.grid(True, axis="y", color=LGREY, lw=0.4)
ax2.set_ylim(0, max(3.0, max(gains) * 1.3))

fig.suptitle(
    "Figure 11 (corrected). Entry-Circulating Flow Adjustment - real SIDRA v10 sweep "
    "(single synthetic roundabout, oversaturated)",
    fontsize=10, fontweight="bold", color="#1F4E79", y=1.02)
fig.tight_layout()
fig.savefig(OUT, dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {OUT}")
print("SIDRA Standard US caps:", std.get("caps"))
print("gains:", gains)
