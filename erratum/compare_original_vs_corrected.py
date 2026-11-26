"""
ERRATUM: compare every published SIDRA Standard US result with its corrected
re-run.  Reads output/ (original, as published) and output/erratum/
(corrected) and writes output/erratum/comparison.json plus a printed summary.

Sites that SIDRA rejected in a run (zero capacity at any parameter value) are
excluded from that run's statistics; "paired" statistics use only the sites
valid in both runs.
"""
import json, sys, io
from pathlib import Path
import numpy as np

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

REPO = Path(__file__).resolve().parents[1]
ORIG = REPO / "output"
CORR = REPO / "output" / "erratum"
PROJ = REPO.parent
res = {}


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# Sites whose OSM inscribed diameter is below 16 m leave a central island of
# 6 ft or less (often negative) once the template's 23 ft circulating width is
# subtracted.  They are mini-roundabouts or OSM mismatches that the template
# geometry cannot represent, so the corrected analysis excludes them.
MIN_ICD_M = 16.0
_osm = load(REPO / "osm" / "parsed.json")
SMALL = sorted(k for k, v in _osm.items()
               if v.get("found") and v.get("icd_m") and v["icd_m"] < MIN_ICD_M)
res["excluded_small_icd"] = {s: _osm[s]["icd_m"] for s in SMALL}


# ---------------------------------------------------------------- Table 1 / Fig 5
def three_model(summary_path):
    s = load(summary_path)
    cf = s["cf_values"]
    out = {}
    for key in ("sidra_standard_us", "hcm2010", "hcm6"):
        rows = {}
        for sid, rec in s["sites"][key].items():
            caps = [r["mean_cap"] for r in sorted(rec["sweep"], key=lambda x: x["cf"])]
            if len(caps) == len(cf) and min(caps) > 0:
                rows[sid] = caps
        out[key] = rows
    return cf, out


def tm_stats(cf, rows, ids=None):
    ids = sorted(rows) if ids is None else sorted(ids)
    m = np.array([rows[i] for i in ids], float)
    i1, i11 = cf.index(1.0), cf.index(1.1)
    mean = m.mean(axis=0)
    return {"n": len(ids), "mean_at_1": round(mean[i1]),
            "p10_at_1": round(np.percentile(m[:, i1], 10)),
            "p90_at_1": round(np.percentile(m[:, i1], 90)),
            "sens_per_0.1_pct": round((mean[i11] - mean[i1]) / mean[i1] * 100, 1)}


cf, o = three_model(ORIG / "model_sweep_summary.json")
_, c = three_model(CORR / "model_sweep_summary.json")
for key in c:
    c[key] = {k: v for k, v in c[key].items() if k not in SMALL}
common_c = set.intersection(*(set(c[k]) for k in c))      # valid in all three models
t1 = {"n_common_corrected": len(common_c)}
for key in o:
    paired = set(o[key]) & set(c[key])
    ratio = [c[key][s][cf.index(1.0)] / o[key][s][cf.index(1.0)] - 1 for s in paired]
    t1[key] = {"original": tm_stats(cf, o[key]), "corrected": tm_stats(cf, c[key], common_c),
               "original_paired": tm_stats(cf, o[key], paired),
               "corrected_paired": tm_stats(cf, c[key], paired),
               "site_change_pct_at_1": [round(100 * min(ratio), 1),
                                        round(100 * float(np.mean(ratio)), 1),
                                        round(100 * max(ratio), 1)],
               "not_in_corrected": sorted(set(o[key]) - set(c[key]))}
for run in ("original", "corrected"):
    h6 = t1["hcm6"][run]["mean_at_1"]
    for key in ("sidra_standard_us", "hcm2010", "hcm6"):
        t1[key][run]["vs_hcm6_pct"] = round((t1[key][run]["mean_at_1"] - h6) / h6 * 100, 1)
res["table1"] = t1


# ---------------------------------------------------------------- EC, HV (47 sites)
def site_map(d, field, drop_small=False):
    return {s["site_id"]: s[field] for s in d["sites"]
            if s.get("ok", True) and s.get(field) and min(s.get("caps") or [0]) > 0
            and not (drop_small and s["site_id"] in SMALL)}


for name, fname, field, labels_key in (
        ("ec_allsites", "ec_allsites/ec_allsites_summary.json", "gain_pct", "ec_labels"),
        ("hv_allsites", "hv_allsites/hv_allsites_summary.json", "chg_pct_vs_6", "hv_labels")):
    do, dc = load(ORIG / fname), load(CORR / fname)
    so, sc = site_map(do, field), site_map(dc, field, drop_small=True)
    paired = sorted(set(so) & set(sc))
    labels = do[labels_key]

    def mean_by_level(sm, ids):
        a = np.array([sm[i] for i in ids], float)
        return {lab: round(float(a[:, j].mean()), 2) for j, lab in enumerate(labels)}

    def range_last(sm, ids):
        a = np.array([sm[i][-1] for i in ids], float)
        return [round(float(a.min()), 2), round(float(a.max()), 2)]

    caps_o = {s["site_id"]: s["caps"] for s in do["sites"] if s["site_id"] in so}
    caps_c = {s["site_id"]: s["caps"] for s in dc["sites"] if s["site_id"] in sc}
    base_idx = 0 if name == "ec_allsites" else labels.index("6%")
    res[name] = {
        "n_original": len(so), "n_corrected": len(sc), "n_paired": len(paired),
        "original": mean_by_level(so, sorted(so)), "corrected": mean_by_level(sc, sorted(sc)),
        "original_paired": mean_by_level(so, paired), "corrected_paired": mean_by_level(sc, paired),
        "last_level_range_original": range_last(so, sorted(so)),
        "last_level_range_corrected": range_last(sc, sorted(sc)),
        "baseline_cap_mean_original_paired":
            round(float(np.mean([caps_o[i][base_idx] for i in paired])), 1),
        "baseline_cap_mean_corrected_paired":
            round(float(np.mean([caps_c[i][base_idx] for i in paired])), 1),
        "rejected_in_corrected": sorted(set(so) - set(sc)),
    }


# ---------------------------------------------------------------- delay (Fig 10)
def delay_stats(d, ids=None):
    pts = [p for p in d["points"] if p.get("delay") is not None
           and (ids is None or p["site"] in ids)]
    fes, vols = d["fe_values"], d["vol_levels"]
    rows = {}
    for v in vols:
        md = {fe: np.mean([p["delay"] for p in pts if p["fe"] == fe and p["vol"] == v])
              for fe in fes}
        vc = np.mean([p["vc"] for p in pts if p["vol"] == v])
        rows[str(v)] = {"vc": round(float(vc), 2),
                        "spread_s": round(float(max(md.values()) - min(md.values())), 1),
                        "mean_delay_fe105": round(float(md[1.05]), 1)}
    return rows


def delay_ok_sites(d):
    ok = set()
    for s in d["sites"]:
        if s.get("points") and all(p.get("delay") is not None and p.get("vc", 0) > 0
                                   for p in s["points"]):
            ok.add(s["site_id"])
    return ok


do, dc = load(ORIG / "delay_allsites/delay_allsites_summary.json"), \
    load(CORR / "delay_allsites/delay_allsites_summary.json")
ok_o, ok_c = delay_ok_sites(do), delay_ok_sites(dc) - set(SMALL)
res["delay_allsites"] = {"n_original": len(ok_o), "n_corrected": len(ok_c),
                         "original": delay_stats(do, ok_o), "corrected": delay_stats(dc, ok_c),
                         "rejected_in_corrected": sorted(ok_o - ok_c)}

# ---------------------------------------------------------------- EC single (Fig 11)
eo, ec = load(ORIG / "ec_sweep_sidra.json"), load(CORR / "ec_sweep_sidra.json")
res["ec_single"] = {m: {"original": eo["models"][m]["gain_pct_vs_None"],
                        "corrected": ec["models"][m]["gain_pct_vs_None"],
                        "caps_original": eo["models"][m]["caps"],
                        "caps_corrected": ec["models"][m]["caps"]}
                    for m in eo["models"]}

# ---------------------------------------------------------------- screening (Sec 4.3)
def screening(d):
    sw = d["sweep"]
    mean = {k: float(np.mean(v["caps"])) for k, v in sw.items() if v["caps"]}
    caps105 = [s["cap_default"] for s in d["sites"] if s.get("cap_default")]
    per01 = [(mean[f"{a:.1f}"] - mean[f"{a + 0.1:.1f}"]) for a in np.arange(0.9, 1.25, 0.1)]
    per01_pct = [(mean[f"{a:.1f}"] - mean[f"{a + 0.1:.1f}"]) / mean[f"{a:.1f}"] * 100
                 for a in np.arange(0.9, 1.25, 0.1)]
    xs = sorted(float(k) for k in mean)
    at105 = float(np.interp(1.05, xs, [mean[f"{x:.1f}"] for x in xs]))   # as in Figure 4
    return {"n_sites": len(caps105), "mean_cap_fe105": round(at105),
            "mean_of_site_caps_fe105": round(float(np.mean(caps105))),
            "mean_cap_fe05": round(mean["0.5"]), "mean_cap_fe20": round(mean["2.0"]),
            "drop_per_0.1_veh_h_range_0.9_1.3": [round(min(per01)), round(max(per01))],
            "drop_per_0.1_pct_range_0.9_1.3": [round(min(per01_pct), 1), round(max(per01_pct), 1)]}


so = load(PROJ / "Task 4" / "figure_data.json")
scr = CORR / "figure_data_corrected.json"
res["screening"] = {"original": screening(so),
                    "corrected": screening(load(scr)) if scr.exists() else None,
                    "failures_corrected": load(scr).get("failures") if scr.exists() else None}

(CORR / "comparison.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
print(json.dumps(res, indent=1)[:12000])
