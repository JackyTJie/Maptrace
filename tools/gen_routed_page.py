#!/usr/bin/env python3
"""Generate MapLibre transport page with REAL routes:
  walking → OSRM foot routing (street-level)
  tube    → Tube graph routing (along actual subway tracks)
"""

import json
import math
import os
import sys
import urllib.request
from datetime import datetime

# --- config ---
SRC = sys.argv[1] if len(sys.argv) > 1 else "gps_data/2026-01-27.txt"
OUT = sys.argv[2] if len(sys.argv) > 2 else "web/2026-01-27-routed.html"
CUT = sys.argv[3] if len(sys.argv) > 3 else ""
TILE_URL = "http://localhost:8088"
OSRM_URL = "http://localhost:5000"
TUBE_GRAPH = "tube-graph.json"

WALK_MAX_SPEED = 3.0
TUBE_MIN_DIST = 2500
BURST_SEC = 120
BURST_M = 15


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# === Tube Router ===

class TubeRouter:
    def __init__(self, graph_path):
        import networkx as nx
        self.G = nx.Graph()
        self.stations = []
        with open(graph_path) as f:
            data = json.load(f)
        self.stations = data["stations"]
        for e in data["edges"]:
            u = tuple(e["from"]) if isinstance(e["from"], list) else e["from"]
            v = tuple(e["to"]) if isinstance(e["to"], list) else e["to"]
            geom = e.get("geometry")
            self.G.add_edge(u, v, weight=e["weight"], geometry=geom)
        # Build station key map
        self._stn_keys = {}
        for s in self.stations:
            self._stn_keys[f"STN_{s['id']}"] = s

    def nearest_station(self, lat, lon):
        best, best_dist = None, float("inf")
        for i, s in enumerate(self.stations):
            d = haversine(lat, lon, s["lat"], s["lon"])
            if d < best_dist:
                best_dist = d
                best = (i, s, d)
        return best

    def route(self, start_lat, start_lon, end_lat, end_lon):
        import networkx as nx
        i1, s1, d1 = self.nearest_station(start_lat, start_lon)
        i2, s2, d2 = self.nearest_station(end_lat, end_lon)
        key1 = f"STN_{s1['id']}"
        key2 = f"STN_{s2['id']}"
        if key1 not in self.G or key2 not in self.G:
            return [], [start_lat, start_lon, end_lat, end_lon], f"{s1['name']} → {s2['name']} (no path)"
        try:
            path = nx.shortest_path(self.G, key1, key2, weight="weight")
        except nx.NetworkXNoPath:
            return [], [start_lat, start_lon, end_lat, end_lon], f"{s1['name']} → {s2['name']} (no path)"
        coords = [[start_lon, start_lat]]
        for n in path:
            geom = None
            for _, _, data in self.G.edges(n, data=True):
                if "geometry" in data:
                    geom = data["geometry"]
                    break
            if geom:
                coords.extend(geom)
        coords.append([end_lon, end_lat])
        return coords, [s1["lon"], s1["lat"], s2["lon"], s2["lat"]], f"{s1['name']} → {s2['name']}"


# === OSRM walking router ===

def osrm_walk(lon1, lat1, lon2, lat2):
    url = f"{OSRM_URL}/route/v1/foot/{lon1},{lat1};{lon2},{lat2}?geometries=geojson&overview=full"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
        if data.get("code") == "Ok" and data.get("routes"):
            return data["routes"][0]["geometry"]["coordinates"]
    except Exception as e:
        print(f"  OSRM error: {e}")
    return None


# === Classification (same as before) ===

def classify_segment(a, b, all_entries):
    dt = (b["time"] - a["time"]).total_seconds()
    dd = haversine(a["lat"], a["lon"], b["lat"], b["lon"])
    speed = dd / dt if dt > 0 else 999
    if dt < BURST_SEC and dd < BURST_M:
        return "skip", dd, dt, speed, "burst"
    if dd >= TUBE_MIN_DIST:
        return "tube", dd, dt, speed, f"jump {dd:.0f}m ≥ {TUBE_MIN_DIST}m"
    if speed > WALK_MAX_SPEED:
        return "tube", dd, dt, speed, f"speed {speed:.1f} m/s"
    if dd > 500 and any(not e["has_gps"] for e in all_entries if a["time"] < e["time"] < b["time"]):
        return "tube", dd, dt, speed, "GPS blackout"
    return "walking", dd, dt, speed, "walk"


# === Main ===

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

# Init tube router (kept for reference, not used for route generation)
# tube = TubeRouter(TUBE_GRAPH)

# Classify and route
point_features = []
line_features = []
tube_markers = []  # red dots for tube start/end
walking_count = 0
tube_count = 0
skip_count = 0

for e in gps_entries:
    point_features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"]]},
        "properties": {"name": e["name"], "time": e["time"].strftime("%H:%M"), "kind": "photo"}
    })

for i in range(len(gps_entries) - 1):
    a = gps_entries[i]
    b = gps_entries[i+1]
    mode, dd, dt, speed, reason = classify_segment(a, b, entries)
    if mode == "skip":
        skip_count += 1
        continue

    if mode == "walking":
        walking_count += 1
        print(f"   {a['time'].strftime('%H:%M')}→{b['time'].strftime('%H:%M')}  {dd:.0f}m  OSRM...", end="")
        coords = osrm_walk(a["lon"], a["lat"], b["lon"], b["lat"])
        if coords:
            print(f"  {len(coords)} pts")
        else:
            coords = [[a["lon"], a["lat"]], [b["lon"], b["lat"]]]
            print("  fallback to straight")
        color = "#2563eb"
        desc = f" 步行 {a['time'].strftime('%H:%M')} → {b['time'].strftime('%H:%M')}"
    else:
        tube_count += 1
        print(f"   {a['time'].strftime('%H:%M')}→{b['time'].strftime('%H:%M')}  {dd:.0f}m  TUBE → red markers only")
        # Don't draw a line; add red marker dots at start and end
        tube_markers.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [a["lon"], a["lat"]]},
            "properties": {"name": a["name"], "time": a["time"].strftime("%H:%M"), "kind": "tube_entry"}
        })
        tube_markers.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [b["lon"], b["lat"]]},
            "properties": {"name": b["name"], "time": b["time"].strftime("%H:%M"), "kind": "tube_exit"}
        })
        continue  # skip line generation for tube

    dsp = round(haversine(a["lat"], a["lon"], b["lat"], b["lon"]))
    dtsp = round((b["time"] - a["time"]).total_seconds())

    line_features.append({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "mode": mode, "stroke": color,
            "from": a["name"], "to": b["name"],
            "from_time": a["time"].strftime("%H:%M"),
            "to_time": b["time"].strftime("%H:%M"),
            "distance": dsp, "duration_sec": dtsp,
            "desc": desc
        }
    })

# Build HTML
point_fc = {"type": "FeatureCollection", "features": point_features}
line_fc = {"type": "FeatureCollection", "features": line_features}
tube_fc = {"type": "FeatureCollection", "features": tube_markers}

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>London {day}  步行街道路线  |   {walking_count}   {tube_count}</title>
<meta name="viewport" content="initial-scale=1,maximum-scale=1,user-scalable=no">
<link rel="stylesheet" href="{TILE_URL}/maplibre-gl.css">
<style>
  html,body,#map{{width:100%;height:100%;margin:0;padding:0}}
  #info{{position:absolute;top:10px;left:10px;z-index:10;background:rgba(255,255,255,.92);
      padding:8px 12px;border-radius:8px;font:13px/1.4 system-ui,sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.2)}}
  #legend{{position:absolute;bottom:30px;right:10px;z-index:10;background:rgba(255,255,255,.92);
      padding:10px 14px;border-radius:8px;font:13px/1.6 system-ui,sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.15)}}
  .leg-swatch{{display:inline-block;width:28px;height:4px;border-radius:2px;vertical-align:middle;margin-right:6px}}
  #toggle-btn{{position:absolute;bottom:140px;right:10px;z-index:10;background:rgba(255,255,255,.92);
      padding:6px 12px;border-radius:8px;font:13px system-ui,sans-serif;cursor:pointer;
      box-shadow:0 1px 4px rgba(0,0,0,.15);user-select:none}}
  #toggle-btn:hover{{background:#f0f0f0}}
  .maplibregl-popup-content{{font:13px/1.5 system-ui,sans-serif;max-width:300px}}
</style>
</head>
<body>
<div id="info">
   {day} ｜ GPS 照片 <b>{len(gps_entries)}</b> 张（截止 {CUT or '全天'}）<br>
  <span style="color:#2563eb">  步行（街道实线）{walking_count} 段</span><br>
  <span style="color:#dc2626">  地铁起/终点 {tube_count} 段</span><br>
  <small>{skip_count} 段连拍跳过 |  大红点 = 地铁站台位置</small>
</div>
<div id="legend">
  <b>图例</b><br>
  <span class="leg-swatch" style="background:#2563eb"></span>  步行（沿街道 OSRM）<br>
  <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#dc2626;border:3px solid #fca5a5;vertical-align:middle;margin-right:4px;margin-left:2px"></span>  地铁上车<br>
  <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#991b1b;border:3px solid #fca5a5;vertical-align:middle;margin-right:4px;margin-left:2px"></span>  地铁下车<br>
  <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#dc2626;border:1.5px solid #fff;vertical-align:middle;margin-right:6px;margin-left:4px"></span> 照片
</div>
<div id="toggle-btn" onclick="toggleCluster()" title="切换照片点位聚合">Disperse</div>
<div id="map"></div>
</body>
<script src="{TILE_URL}/maplibre-gl.js"></script>
<script>
const POINTS = {json.dumps(point_fc)};
const LINES  = {json.dumps(line_fc)};
const TUBE   = {json.dumps(tube_fc)};

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
    layout: {{'line-join':'round','line-cap':'round'}},
    paint: {{'line-color': '#2563eb', 'line-width': 3.5, 'line-opacity': 0.8}}
  }});

  // -- Tube markers (entry = bright red, exit = dark red) --
  map.addSource('tube-markers', {{type: 'geojson', data: TUBE}});
  map.addLayer({{
    id: 'tube-entry', type: 'circle', source: 'tube-markers',
    filter: ['==', ['get', 'kind'], 'tube_entry'],
    paint: {{
      'circle-color': '#dc2626', 'circle-radius': 8,
      'circle-stroke-width': 3, 'circle-stroke-color': '#fca5a5'
    }}
  }});
  map.addLayer({{
    id: 'tube-exit', type: 'circle', source: 'tube-markers',
    filter: ['==', ['get', 'kind'], 'tube_exit'],
    paint: {{
      'circle-color': '#991b1b', 'circle-radius': 8,
      'circle-stroke-width': 3, 'circle-stroke-color': '#fca5a5'
    }}
  }});

  // -- Photo points (clustered) --
  map.addSource('points', {{type:'geojson', data: POINTS, cluster: true, clusterMaxZoom: 14, clusterRadius: 30}});
  map.addLayer({{id:'clusters', type:'circle', source:'points', filter:['has','point_count'],
    paint:{{'circle-color':['step',['get','point_count'],'#1d4ed8',10,'#7c3aed',30,'#db2777'],
    'circle-radius':['step',['get','point_count'],18,10,22,30,26],'circle-stroke-width':2,'circle-stroke-color':'#fff'}}}});
  map.addLayer({{id:'cluster-count', type:'symbol', source:'points', filter:['has','point_count'],
    layout:{{'text-field':'{{point_count_abbreviated}}','text-font':['Noto Sans Regular'],'text-size':12}}, paint:{{'text-color':'#fff'}}}});
  map.addLayer({{id:'unclustered', type:'circle', source:'points', filter:['!',['has','point_count']],
    paint:{{'circle-color':'#dc2626','circle-radius':4,'circle-stroke-width':1.5,'circle-stroke-color':'#fff'}}}});

  // -- Unclustered ALL points (hidden by default) --
  map.addSource('points-all', {{type:'geojson', data: POINTS}});
  map.addLayer({{
    id: 'unclustered-all', type: 'circle', source: 'points-all', layout: {{visibility:'none'}},
    paint: {{'circle-color':'#dc2626','circle-radius':3.5,'circle-stroke-width':1,'circle-stroke-color':'#fff','circle-opacity':0.85}}
  }});

  // -- Toggle clustering --
  let clustered = true;
  window.toggleCluster = function() {{
    clustered = !clustered;
    const btn = document.getElementById('toggle-btn');
    const visOn = clustered ? 'visible' : 'none';
    const visOff = clustered ? 'none' : 'visible';
    btn.textContent = clustered ? 'Disperse' : 'Cluster';
    ['clusters','cluster-count','unclustered'].forEach(id => map.setLayoutProperty(id, 'visibility', visOn));
    map.setLayoutProperty('unclustered-all', 'visibility', visOff);
  }};

  // Popups
  const popup = new maplibregl.Popup({{closeButton: false, offset: 12}});

  map.on('click', 'unclustered', e => {{
    const p = e.features[0].properties;
    popup.setLngLat(e.lngLat).setHTML(`<b>${{p.name}}</b><br> ${{p.time}}<br><code>${{e.lngLat.lat.toFixed(6)}}, ${{e.lngLat.lng.toFixed(6)}}</code>`).addTo(map);
  }});
  map.on('click', 'unclustered-all', e => {{
    const p = e.features[0].properties;
    popup.setLngLat(e.lngLat).setHTML(`<b>${{p.name}}</b><br> ${{p.time}}<br><code>${{e.lngLat.lat.toFixed(6)}}, ${{e.lngLat.lng.toFixed(6)}}</code>`).addTo(map);
  }});
  map.on('click', 'clusters', e => {{
    const f = map.queryRenderedFeatures(e.point, {{layers:['clusters']}})[0];
    map.easeTo({{center: f.geometry.coordinates, zoom: map.getZoom()+2}});
  }});
  map.on('click', 'walking-lines', e => {{
    const p = e.features[0].properties;
    const spd = Math.round(p.distance/Math.max(p.duration_sec,1)*36)/10;
    popup.setLngLat(e.lngLat)
      .setHTML(`<span style="color:#2563eb"> <b>步行</b></span><br>${{p.from_time}}→${{p.to_time}}<br>${{p.distance}}m ｜ ${{spd}} km/h<br><small>路线 = 街道实线 (OSRM)</small>`)
      .addTo(map);
  }});
  map.on('click', 'tube-entry', e => {{
    const p = e.features[0].properties;
    popup.setLngLat(e.lngLat).setHTML(`<span style="color:#dc2626"> <b>地铁上车</b></span><br>${{p.name}}<br>${{p.time}}`).addTo(map);
  }});
  map.on('click', 'tube-exit', e => {{
    const p = e.features[0].properties;
    popup.setLngLat(e.lngLat).setHTML(`<span style="color:#991b1b"> <b>地铁下车</b></span><br>${{p.name}}<br>${{p.time}}`).addTo(map);
  }});
  map.on('mouseenter', 'unclustered', () => (map.getCanvas().style.cursor='pointer'));
  map.on('mouseleave', 'unclustered', () => (map.getCanvas().style.cursor=''));
  map.on('mouseenter', 'unclustered-all', () => (map.getCanvas().style.cursor='pointer'));
  map.on('mouseleave', 'unclustered-all', () => (map.getCanvas().style.cursor=''));
  map.on('mouseenter', 'walking-lines', () => (map.getCanvas().style.cursor='pointer'));
  map.on('mouseenter', 'tube-entry', () => (map.getCanvas().style.cursor='pointer'));
  map.on('mouseenter', 'tube-exit', () => (map.getCanvas().style.cursor='pointer'));

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

print(f"\n→ {OUT}")
print(f"    walking: {walking_count} (OSRM street-level)")
print(f"    tube:    {tube_count} (tube track graph)")
print(f"   skipped:   {skip_count} (burst)")
print(f"   points:    {len(point_features)}")
