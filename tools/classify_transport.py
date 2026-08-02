#!/usr/bin/env python3
"""Classify transportation mode between consecutive GPS photos:
  walking (≤3 m/s, short intervals) → blue line
  tube (>3 m/s, GPS blackout, or long jump) → red line
  burst (<120s AND <15m, same-location cluster) → no line
"""

import math
import sys
from datetime import datetime

SRC = sys.argv[1] if len(sys.argv) > 1 else "gps_data/2026-01-27.txt"
CUT = sys.argv[2] if len(sys.argv) > 2 else ""  # e.g. "22:30"

WALK_MAX_SPEED = 3.0        # m/s
BURST_SEC = 120             # seconds
BURST_M = 15                # metres

SKIPPED = "skip"
WALKING = "walking"
TUBE = "tube"
COLORS = {SKIPPED: None, WALKING: "#2563eb", TUBE: "#dc2626"}


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# Parse all lines (both GPS and no GPS) to enable GPS-gap detection
entries = []
with open(SRC, encoding="utf-8") as fh:
    for line in fh:
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        fname, ts, gps = parts[0], parts[1], parts[2]
        lat = lon = None
        if gps != "no GPS" and "," in gps:
            lat, lon = map(float, gps.split(","))
        entries.append({
            "name": fname,
            "time": datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
            "lat": lat,
            "lon": lon,
            "has_gps": lat is not None
        })

entries.sort(key=lambda e: e["time"])
if CUT:
    day = SRC.split("/")[-1].replace(".txt", "")
    cut_time = datetime.strptime(f"{day} {CUT}", "%Y-%m-%d %H:%M")
    entries = [e for e in entries if e["time"] <= cut_time]
gps_entries = [e for e in entries if e["has_gps"]]

print(f"Total photos: {len(entries)} | with GPS: {len(gps_entries)}")
print()

segments = []
for i in range(len(gps_entries) - 1):
    a = gps_entries[i]
    b = gps_entries[i+1]
    dt = (b["time"] - a["time"]).total_seconds()
    dd = haversine(a["lat"], a["lon"], b["lat"], b["lon"])
    speed = dd / dt if dt > 0 else 999

    # Burst detection
    if dt < BURST_SEC and dd < BURST_M:
        mode = SKIPPED
        reason = f"burst ({dd:.0f}m, {dt:.0f}s)"
    elif speed > WALK_MAX_SPEED:
        mode = TUBE
        reason = f"speed {speed:.1f} m/s"
    elif dd > 500 and any(not e["has_gps"] for e in entries if a["time"] < e["time"] < b["time"]):
        mode = TUBE
        reason = f"GPS blackout + {dd:.0f}m gap"
    else:
        mode = WALKING
        reason = f"walk {speed:.2f} m/s, {dd:.0f}m"

    segments.append({
        "from": a, "to": b,
        "dt": dt, "dd": dd, "speed": speed,
        "mode": mode, "reason": reason
    })

# Report
for s in segments:
    flag = {"walking": "🚶", "tube": "🚇", "skip": "  "}[s["mode"]]
    print(f"{flag} {s['from']['time'].strftime('%H:%M')} → {s['to']['time'].strftime('%H:%M')}  "
          f"{s['dd']:6.0f}m  {s['dt']:5.0f}s  {s['speed']:4.1f}m/s  [{s['mode']:7s}]  {s['reason']}")

walking_count = sum(1 for s in segments if s["mode"] == WALKING)
tube_count = sum(1 for s in segments if s["mode"] == TUBE)
skip_count = sum(1 for s in segments if s["mode"] == SKIPPED)
print(f"\n🚶 walking segments: {walking_count}")
print(f"🚇 tube segments:    {tube_count}")
print(f"   skipped (burst):  {skip_count}")
