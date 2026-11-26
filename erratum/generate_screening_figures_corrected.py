"""
ERRATUM: redraw report Figures 3 and 4 from the corrected screening re-run,
using the original plotting code in Task 4/generate_figures.py.
Writes Task 6/Erratum/Figure3_CapacityDistribution_corrected.png and
Figure4_CapacityVsFe_corrected.png.
"""
import json, sys, importlib.util
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
DATA = PROJ / "sidra-calibration" / "output" / "erratum" / "figure_data_corrected.json"
OUT = PROJ / "Task 6" / "Erratum"
OUT.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location("gf", PROJ / "Task 4" / "generate_figures.py")
gf = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]]
src = (PROJ / "Task 4" / "generate_figures.py").read_text(encoding="utf-8")
main_at = src.find('if __name__ == "__main__"')
code = src[:main_at] if main_at > 0 else src
gf.__dict__["__file__"] = str(PROJ / "Task 4" / "generate_figures.py")
exec(compile(code, "generate_figures.py", "exec"), gf.__dict__)

gf.DATA = json.loads(DATA.read_text())

# The original histogram bins are fixed at range(800, 1800, 75); widen them to
# cover the corrected capacities.
_caps = [s["cap_default"] for s in gf.DATA["sites"] if s.get("cap_default")]
_lo, _hi = int(min(_caps) // 50 * 50), int(max(_caps) // 50 * 50 + 100)
_builtin_range = range
gf.range = lambda *a: _builtin_range(_lo, _hi, 50) if a == (800, 1800, 75) else _builtin_range(*a)
gf.OUT = OUT
n = len(gf.DATA["sites"])


class _Renamer:
    """Route savefig calls to *_corrected.png and fix the site count in titles."""
    def __init__(self, fig):
        self.fig = fig

    def __getattr__(self, name):
        return getattr(self.fig, name)

    def savefig(self, path, *a, **k):
        p = Path(path)
        return self.fig.savefig(p.with_name(p.stem + "_corrected.png"), *a, **k)


import matplotlib.pyplot as plt
_orig_subplots = plt.subplots


def _subplots(*a, **k):
    fig, ax = _orig_subplots(*a, **k)
    return _Renamer(fig), ax


gf.plt.subplots = _subplots
_orig_close = plt.close
gf.plt.close = lambda f=None: _orig_close(f.fig if isinstance(f, _Renamer) else f)

# Retitle: mark as corrected and use the actual site count
import matplotlib.axes, matplotlib.figure
_t, _st, _pl = (matplotlib.axes.Axes.set_title, matplotlib.figure.Figure.suptitle,
                matplotlib.axes.Axes.plot)


def _fix(text):
    return (str(text).replace("Figure 4.", "Figure 4 (corrected).")
            .replace("Figure 3.", "Figure 3 (corrected).")
            .replace("58 California", f"{n} California").replace("(58 sites)", f"({n} sites)")
            .replace("SIDRA Standard model", "SIDRA Standard US, US Customary setup"))


def _plot(self, *a, **k):
    if "label" in k:
        k["label"] = _fix(k["label"])
    return _pl(self, *a, **k)


matplotlib.axes.Axes.set_title = lambda self, label, *a, **k: _t(self, _fix(label), *a, **k)
matplotlib.figure.Figure.suptitle = lambda self, t, *a, **k: _st(self, _fix(t), *a, **k)
matplotlib.axes.Axes.plot = _plot
gf.figure2()   # Figure 4, capacity vs fe
gf.figure3()   # Figure 3, capacity distribution
print(f"Corrected Figures 3 and 4 written to {OUT} ({n} sites)")
