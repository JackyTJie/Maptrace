#!/usr/bin/env python3
"""Generate a MapLibre HTML page marking GPS points from one gps_data txt file."""

import json
import os
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "gps_data/2026-01-27.txt"
OUT = sys.argv[2] if len(sys.argv) > 2 else "web/2026-01-27.html"
TILE_URL = "http://localhost:8088"

day = os.path.basename(SRC).replace(".txt", "")

features = []
with open(SRC, encoding="utf-8") as fh:
    for line in fh:
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        fname, ts, gps = parts[0], parts[1], parts[2]
        if gps == "no GPS" or "," not in gps:
            continue
        lat, lon = gps.split(",")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": {"name": fname, "time": ts},
        })

fc = {"type": "FeatureCollection", "features": features}

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>London {day} GPS 标记点 ({len(features)})</title>
<meta name="viewport" content="initial-scale=1,maximum-scale=1,user-scalable=no">
<link rel="stylesheet" href="{TILE_URL}/maplibre-gl.css">
<style>
  html,body,#map{{width:100%;height:100%;margin:0;padding:0}}
  #info{{position:absolute;top:10px;left:10px;z-index:10;background:rgba(255,255,255,.92);
        padding:8px 12px;border-radius:8px;font:13px/1.4 system-ui,sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.2)}}
  .maplibregl-popup-content{{font:13px/1.5 system-ui,sans-serif}}
</style>
</head>
<body>
<div id="info">📷 {day} ｜ 有 GPS 的照片：<b>{len(features)}</b> 张<br><small>点击标记查看照片名与拍摄时间</small></div>
<div id="map"></div>
<script src="{TILE_URL}/maplibre-gl.js"></script>
<script>
const POINTS = {json.dumps(fc)};

const map = new maplibregl.Map({{
  container: 'map',
  style: '{TILE_URL}/styles/basic-preview/style.json',
  center: [-0.1, 51.51],
  zoom: 11,
  attributionControl: {{compact: true}}
}});

map.on('load', () => {{
  map.addSource('photos', {{
    type: 'geojson',
    data: POINTS,
    cluster: true,
    clusterMaxZoom: 14,
    clusterRadius: 42
  }});

  map.addLayer({{
    id: 'clusters',
    type: 'circle',
    source: 'photos',
    filter: ['has', 'point_count'],
    paint: {{
      'circle-color': ['step', ['get', 'point_count'], '#1d4ed8', 10, '#7c3aed', 30, '#db2777'],
      'circle-radius': ['step', ['get', 'point_count'], 18, 10, 22, 30, 26],
      'circle-stroke-width': 2,
      'circle-stroke-color': '#fff'
    }}
  }});

  map.addLayer({{
    id: 'cluster-count',
    type: 'symbol',
    source: 'photos',
    filter: ['has', 'point_count'],
    layout: {{
      'text-field': '{{point_count_abbreviated}}',
      'text-font': ['Noto Sans Regular'],
      'text-size': 12
    }},
    paint: {{'text-color': '#fff'}}
  }});

  map.addLayer({{
    id: 'unclustered',
    type: 'circle',
    source: 'photos',
    filter: ['!', ['has', 'point_count']],
    paint: {{
      'circle-color': '#dc2626',
      'circle-radius': 6,
      'circle-stroke-width': 2,
      'circle-stroke-color': '#fff'
    }}
  }});

  const popup = new maplibregl.Popup({{closeButton: false, offset: 12}});
  map.on('click', 'unclustered', (e) => {{
    const p = e.features[0].properties;
    popup.setLngLat(e.lngLat)
      .setHTML(`<b>${{p.name}}</b><br>${{p.time}}<br><code>${{e.lngLat.lat.toFixed(6)}}, ${{e.lngLat.lng.toFixed(6)}}</code>`)
      .addTo(map);
  }});
  map.on('click', 'clusters', (e) => {{
    const f = map.queryRenderedFeatures(e.point, {{layers: ['clusters']}})[0];
    map.easeTo({{center: f.geometry.coordinates, zoom: map.getZoom() + 2}});
  }});

  map.on('mouseenter', 'unclustered', () => (map.getCanvas().style.cursor = 'pointer'));
  map.on('mouseleave', 'unclustered', () => (map.getCanvas().style.cursor = ''));

  const coords = POINTS.features.map(f => f.geometry.coordinates);
  map.fitBounds(coords.reduce((b, c) => [
    [Math.min(b[0][0], c[0]), Math.min(b[0][1], c[1])],
    [Math.max(b[1][0], c[0]), Math.max(b[1][1], c[1])]
  ], [[180, 90], [-180, -90]]), {{padding: 60, maxZoom: 15}});
}});
</script>
</body>
</html>
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    fh.write(html)
print(f"written {OUT} ({len(features)} points)")
