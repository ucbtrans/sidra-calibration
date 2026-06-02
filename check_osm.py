import json
from pathlib import Path

osm   = json.loads((Path(__file__).parent / "osm" / "parsed.json").read_text())
data  = json.loads((Path(__file__).parent.parent / "Task 4" / "figure_data.json").read_text())
sites = data["sites"]

MIN_ICD = 8.0   # metres — below this we assume OSM found the wrong feature

print(f"{'Site ID':<22}  {'ICD(m)':>7}  {'Appr':>5}  {'cap':>6}  Status")
print("-" * 65)
usable, skipped = [], []
for s in sites:
    sid  = s["site_id"]
    o    = osm.get(sid, {})
    found = o.get("found", False)
    icd   = o.get("icd_m")
    nappr = len(o.get("approach_ways", []))
    cap   = s["cap_default"]

    if not found:
        reason = o.get("warning", "not found")[:35]
        status = f"SKIP — {reason}"
        skipped.append((sid, reason))
    elif icd is not None and icd < MIN_ICD:
        reason = f"ICD={icd}m < {MIN_ICD}m"
        status = f"SKIP — {reason}"
        skipped.append((sid, reason))
    else:
        status = "OK"
        usable.append(sid)

    icd_s = f"{icd}" if icd else "?"
    print(f"{sid:<22}  {icd_s:>7}  {nappr:>5}  {cap:>6}  {status}")

print(f"\nUsable: {len(usable)}/58   Skipped: {len(skipped)}/58")
print("\nSkipped sites:")
for sid, reason in skipped:
    print(f"  {sid}: {reason}")
