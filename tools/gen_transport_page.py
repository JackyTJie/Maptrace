#!/usr/bin/env python3
"""Generate MapLibre page with transport-classified lines + GPS markers."""

import json
import math
import os
import sys
from datetime import datetime

SRC = sys.argv[1] if len(sys.argv) > 1 else "gps_data/2026-01-27.txt"
OUT = sys.argv[2] if len(sys.argv) > 2 else "web/2026-01-27-transport.html"
CUT = sys.argv[3] if len(sys.argv) > 3 else ""  # e.g. "22:30" to drop later photos
TILE_URL = "http://localhost:8088"

WALK_MAX_SPEED = 3.0
BURST_SEC = 120
BURST_M = 15


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# Parse
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
            "name": fname, "time": datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
            "lat": lat, "lon": lon, "has_gps": lat is not None
        })

entries.sort(key=lambda e: e["time"])
day = os.path.basename(SRC).replace(".txt", "")

if CUT:
    cut_time = datetime.strptime(f"{day} {CUT}", "%Y-%m-%d %H:%M")
    entries = [e for e in entries if e["time"] <= cut_time]
gps_entries = [e for e in entries if e["has_gps"]]

# Classify segments
segments = []
for i in range(len(gps_entries) - 1):
    a = gps_entries[i]
    b = gps_entries[i+1]
    dt = (b["time"] - a["time"]).total_seconds()
    dd = haversine(a["lat"], a["lon"], b["lat"], b["lon"])
    speed = dd / dt if dt > 0 else 999
    if dt < BURST_SEC and dd < BURST_M:
        mode = "skip"
    elif speed > WALK_MAX_SPEED:
        mode = "tube"
    elif dd > 500 and any(not e["has_gps"] for e in entries if a["time"] < e["time"] < b["time"]):
        mode = "tube"
    else:
        mode = "walking"
    segments.append({"from": a, "to": b, "mode": mode})

# GeoJSON
point_features = []
for e in gps_entries:
    point_features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"]]},
        "properties": {"name": e["name"], "time": e["time"].strftime("%H:%M")}
    })

line_features = []
for s in segments:
    if s["mode"] == "skip":
        continue
    color = "#dc2626" if s["mode"] == "tube" else "#2563eb"
    line_features.append({
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [s["from"]["lon"], s["from"]["lat"]],
                [s["to"]["lon"], s["to"]["lat"]]
            ]
        },
        "properties": {
            "mode": s["mode"],
            "stroke": color,
            "from": s["from"]["name"],
            "to": s["to"]["name"],
            "from_time": s["from"]["time"].strftime("%H:%M"),
            "to_time": s["to"]["time"].strftime("%H:%M"),
            "distance": round(haversine(s["from"]["lat"], s["from"]["lon"], s["to"]["lat"], s["to"]["lon"])),
            "duration_sec": round((s["to"]["time"] - s["from"]["time"]).total_seconds())
        }
    })

point_fc = {"type": "FeatureCollection", "features": point_features}
line_fc = {"type": "FeatureCollection", "features": line_features}

walking_lines = sum(1 for s in segments if s["mode"] == "walking")
tube_lines = sum(1 for s in segments if s["mode"] == "tube")
skipped = sum(1 for s in segments if s["mode"] == "skip")

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>London {day} 交通方式分析  |  🚶 {walking_lines} walking  🚇 {tube_lines} tube  | {skipped} bursts skipped</title>
<meta name="viewport" content="initial-scale=1,maximum-scale=1,user-scalable=no">
<link rel="stylesheet" href="{TILE_URL}/maplibre-gl.css">
<style>
  html,body,#map{{width:100%;height:100%;margin:0;padding:0}}
  #legend{{position:absolute;bottom:30px;right:10px;z-index:10;background:rgba(255,255,255,.92);
      padding:10px 14px;border-radius:8px;font:13px/1.6 system-ui,sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.15)}}
  .leg-swatch{{display:inline-block;width:28px;height:4px;border-radius:2px;vertical-align:middle;margin-right:6px}}
  #info{{position:absolute;top:10px;left:10px;z-index:10;background:rgba(255,255,255,.92);
      padding:8px 12px;border-radius:8px;font:13px/1.4 system-ui,sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.2)}}
  .maplibregl-popup-content{{font:13px/1.5 system-ui,sans-serif;max-width:300px}}
</style>
</head>
<body>
<div id="info">
  📅 {day} ｜ 有 GPS 的照片：<b>{len(gps_entries)}</b> 张<br>
  <span style="color:#2563eb">━ 🚶 walking ×{walking_lines}</span><br>
  <span style="color:#dc2626">━ 🚇 tube ×{tube_lines}</span><br>
  <small>共 {len(segments)} 段，{skipped} 段连拍跳过</small>
</div>
<div id="legend">
  <b>图例</b><br>
  <span class="leg-swatch" style="background:#2563eb"></span> 🚶 步行<br>
  <span class="leg-swatch" style="background:#dc2626"></span> 🚇 地铁<br>
  <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#dc2626;border:2px solid #fff;vertical-align:middle;margin-right:6px;margin-left:4px"></span> 照片定位
</div>
<div id="map"></div>
<script src="{TILE_URL}/maplibre-gl.js"></script>
<script>
const POINTS = {json.dumps(point_fc)};
const LINES  = {json.dumps(line_fc)};

const map = new maplibregl.Map({{
  container: 'map',
  style: '{TILE_URL}/styles/basic-preview/style.json',
  center: [-0.1, 51.51],
  zoom: 11
}});

map.on('load', () => {{
  // -- Walking lines --
  map.addSource('walking', {{
    type: 'geojson',
    data: {{type:'FeatureCollection', features: LINES.features.filter(f => f.properties.mode === 'walking')}}
  }});
  map.addLayer({{
    id: 'walking-lines', type: 'line', source: 'walking',
    layout: {{'line-join': 'round', 'line-cap': 'round'}},
    paint: {{'line-color': '#2563eb', 'line-width': 3, 'line-opacity': 0.75}}
  }});

  // -- Tube lines --
  map.addSource('tube', {{
    type: 'geojson',
    data: {{type:'FeatureCollection', features: LINES.features.filter(f => f.properties.mode === 'tube')}}
  }});
  map.addLayer({{
    id: 'tube-lines', type: 'line', source: 'tube',
    layout: {{'line-join': 'round', 'line-cap': 'round'}},
    paint: {{'line-color': '#dc2626', 'line-width': 4, 'line-opacity': 0.75}}
  }});

  // -- Points (clustered as before) --
  map.addSource('points', {{type:'geojson', data: POINTS, cluster: true, clusterMaxZoom: 14, clusterRadius: 30}});

  map.addLayer({{
    id: 'clusters', type: 'circle', source: 'points',
    filter: ['has', 'point_count'],
    paint: {{
      'circle-color': ['step', ['get', 'point_count'], '#1d4ed8', 10, '#7c3aed', 30, '#db2777'],
      'circle-radius': ['step', ['get', 'point_count'], 18, 10, 22, 30, 26],
      'circle-stroke-width': 2, 'circle-stroke-color': '#fff'
    }}
  }});
  map.addLayer({{
    id: 'cluster-count', type: 'symbol', source: 'points',
    filter: ['has', 'point_count'],
    layout: {{'text-field': '{{point_count_abbreviated}}', 'text-font': ['Noto Sans Regular'], 'text-size': 12}},
    paint: {{'text-color': '#fff'}}
  }});
  map.addLayer({{
    id: 'unclustered', type: 'circle', source: 'points',
    filter: ['!', ['has', 'point_count']],
    paint: {{'circle-color': '#dc2626', 'circle-radius': 5, 'circle-stroke-width': 2, 'circle-stroke-color': '#fff'}}
  }});

  // Popups: point click = photo info; line click = segment stats
  const popup = new maplibregl.Popup({{closeButton: false, offset: 12}});
  map.on('click', 'unclustered', (e) => {{
    const p = e.features[0].properties;
    popup.setLngLat(e.lngLat)
      .setHTML(`<b>${{p.name}}</b><br>🕐 ${{p.time}}<br><code>${{e.lngLat.lat.toFixed(6)}}, ${{e.lngLat.lng.toFixed(6)}}</code>`)
      .addTo(map);
  }});
  map.on('click', 'clusters', (e) => {{
    const f = map.queryRenderedFeatures(e.point, {{layers:['clusters']}})[0];
    map.easeTo({{center: f.geometry.coordinates, zoom: map.getZoom() + 2}});
  }});
  map.on('click', 'walking-lines', (e) => {{
    const p = e.features[0].properties;
    const speed = Math.round(p.distance / Math.max(p.duration_sec, 1) * 36) / 10;
    popup.setLngLat(e.lngLat)
      .setHTML(`<span style="color:#2563eb">🚶 <b>步行</b></span><br>${{p.from_time}} → ${{p.to_time}}　${{p.duration_sec}}s<br>${{p.distance}}m ｜ ${{speed}} km/h`)
      .addTo(map);
  }});
  map.on('click', 'tube-lines', (e) => {{
    const p = e.features[0].properties;
    const speed = Math.round(p.distance / Math.max(p.duration_sec, 1) * 36) / 10;
    popup.setLngLat(e.lngLat)
      .setHTML(`<span style="color:#dc2626">🚇 <b>地铁</b></span><br>${{p.from_time}} → ${{p.to_time}}　${{p.duration_sec}}s<br>${{p.distance}}m ｜ ${{speed}} km/h`)
      .addTo(map);
  }});
  map.on('mouseenter', 'unclustered', () => (map.getCanvas().style.cursor = 'pointer'));
  map.on('mouseleave', 'unclustered', () => (map.getCanvas().style.cursor = ''));
  map.on('mouseenter', 'walking-lines', () => (map.getCanvas().style.cursor = 'pointer'));
  map.on('mouseenter', 'tube-lines', () => (map.getCanvas().style.cursor = 'pointer'));

  // Fit to points
  const coords = POINTS.features.map(f => f.geometry.coordinates);
  map.fitBounds(coords.reduce((b,c) => [[Math.min(b[0][0],c[0]),Math.min(b[0][1],c[1])],[Math.max(b[1][0],c[0]),Math.max(b[1][1],c[1])]], [[180,90],[-180,-90]]), {{padding:60, maxZoom:14}});
}});
</script>
</body>
</html>
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    fh.write(html)
print(f"written {OUT}")
print(f"  points: {len(point_features)}")
print(f"  walking lines: {walking_lines} (blue)")
print(f"  tube lines: {tube_lines} (red)")
print(f"  skipped bursts: {skipped}")
