"""
generate_delay_allsites_figure.py - plot the inventory-wide REAL SIDRA delay
study (output of run_delay_sweep_allsites.py).

Aggregates by VOLUME level (the controlled variable) rather than v/c bins, so
the fe curves are clean: control delay is insensitive to fe at low demand and
fans out as demand drives the sites into saturation.
"""
import json, sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", line_buffering=True)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DATA = Path(__file__).resolve().parents[1] / "output" / "erratum" / "delay_allsites" / "delay_allsites_summary.json"
OUT  = Path(__file__).resolve().parents[2] / "Task 6" / "Erratum" / "Fig10_DelayReal_corrected.png"

d = json.loads(DATA.read_text(encoding="utf-8"))
pts = d["points"]
N_SITES = len({p["site"] for p in pts})
fes = d["fe_values"]
vols = d["vol_levels"]

# Aggregate by (fe, vol): mean delay and mean v/c across sites
def mean_delay(fe, vol):
    xs = [p["delay"] for p in pts if p["fe"] == fe and p["vol"] == vol]
    return float(np.mean(xs)) if xs else None
def mean_vc(fe, vol):
    xs = [p["vc"] for p in pts if p["fe"] == fe and p["vol"] == vol]
    return float(np.mean(xs)) if xs else None

# mean v/c across all fe at each volume (for x tick annotation)
vc_at_vol = [float(np.mean([p["vc"] for p in pts if p["vol"] == v])) for v in vols]

GREY, LGREY = "#303030", "#D0D0D0"
FE_COL = {min(fes): "#2E7D32", sorted(fes)[len(fes)//2]: "#1F4E79", max(fes): "#C0392B"}

plt.rcParams.update({"font.family": "Arial", "font.size": 9,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.labelcolor": GREY, "xtick.color": GREY, "ytick.color": GREY})

fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
fig.patch.set_facecolor("white")
xlabels = [f"{v}\n(v/c~{vc:.1f})" for v, vc in zip(vols, vc_at_vol)]
x = np.arange(len(vols))

# Panel A - mean delay vs demand, one line per fe
ax = axes[0]
for fe in fes:
    ys = [mean_delay(fe, v) for v in vols]
    ax.plot(x, ys, "-o", color=FE_COL.get(fe, GREY), lw=2.0, ms=5, label=f"fe = {fe}")
ax.set_xticks(x); ax.set_xticklabels(xlabels, fontsize=7.5)
ax.set_xlabel("Total demand (veh/movement)", fontsize=9)
ax.set_ylabel("Mean control delay (s/veh)", fontsize=9)
ax.set_title(f"A. Delay vs demand, by calibration parameter\n({N_SITES} sites, SIDRA Standard US)",
             fontsize=9, fontweight="bold", color=GREY)
ax.legend(fontsize=8, framealpha=0.9)
ax.grid(True, axis="y", color=LGREY, lw=0.4)

# Panel B - delay spread across fe at each demand level
ax2 = axes[1]
spread = []
for v in vols:
    vals = [mean_delay(fe, v) for fe in fes if mean_delay(fe, v) is not None]
    spread.append(max(vals) - min(vals) if len(vals) >= 2 else 0.0)
ax2.bar(x, spread, 0.6, color="#1F4E79")
for xi, sp in zip(x, spread):
    ax2.text(xi, sp, f"{sp:.1f}s" if sp < 10 else f"{sp:.0f}s",
             ha="center", va="bottom", fontsize=8.5)
ax2.set_xticks(x); ax2.set_xticklabels(xlabels, fontsize=7.5)
ax2.set_xlabel("Total demand (veh/movement)", fontsize=9)
ax2.set_ylabel("Delay spread across fe = 0.9 to 1.2 (s/veh)", fontsize=9)
ax2.set_title("B. Sensitivity of delay to fe\n(near zero until saturation, then large)",
              fontsize=9, fontweight="bold", color=GREY)
ax2.grid(True, axis="y", color=LGREY, lw=0.4)

fig.suptitle(
    "Figure 10 (corrected). Control delay vs calibration parameter and demand - "
    f"real SIDRA v10 ({N_SITES} sites, SIDRA Standard US)",
    fontsize=10, fontweight="bold", color="#1F4E79", y=1.02)
fig.tight_layout()
fig.savefig(OUT, dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {OUT}")
print("v/c at each volume:", [round(v, 2) for v in vc_at_vol])
for fe in fes:
    print(f"  fe={fe}: delay = {[round(mean_delay(fe,v),1) for v in vols]}")
print("delay spread across fe:", [round(s, 1) for s in spread])
