#!/usr/bin/env python3
"""Build London tube station graph from OSM subway tracks + stations.
Output: JSON graph suitable for routing between stations."""

import json
import math
import sys

STATIONS_FILE = "tube-stations.geojsons"
WAYS_FILE = "tube-ways.geojsons"
OUT_FILE = "tube-graph.json"
SNAP_RADIUS_M = 150  # max distance to snap a station to the track network


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# === Load stations ===
stations = []
# Only keep actual railway stations (filter out bus/ferry stops from the export)
SKIP_TAGS = {"bus", "ferry", "tram", "light_rail"}
with open(STATIONS_FILE) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        geom = obj.get("geometry")
        props = obj.get("properties", {})
        if geom and geom["type"] == "Point":
            coords = geom["coordinates"]
            name = props.get("name", "?")
            # Skip non-subway stops
            is_subway = props.get("station") == "subway" or props.get("railway") in ("station", "halt")
            has_bus = props.get("bus") == "yes"
            if has_bus and not is_subway:
                continue
            stations.append({"id": len(stations), "name": name, "lat": coords[1], "lon": coords[0]})

print(f"Loaded {len(stations)} station nodes")

# === Load track ways, build adjacency ===
# Build a graph keyed by (lon, lat) tuples (rounded to 6 decimals as node key)
import networkx as nx

G = nx.Graph()

node_set = set()  # track network nodes

with open(WAYS_FILE) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        geom = obj.get("geometry")
        if geom and geom["type"] == "LineString":
            coords = geom["coordinates"]
            # Each segment of the way is an edge
            for i in range(len(coords) - 1):
                a = (round(coords[i][0], 6), round(coords[i][1], 6))
                b = (round(coords[i+1][0], 6), round(coords[i+1][1], 6))
                d = haversine(a[1], a[0], b[1], b[0])
                G.add_edge(a, b, weight=d, geometry=[coords[i], coords[i+1]])
                node_set.add(a)
                node_set.add(b)

print(f"Track graph: {len(node_set)} nodes, {len(G.edges)} edges")

# === Snap each station to nearest track node ===
station_snaps = []
unmatched = []
for st in stations:
    best_node = None
    best_dist = float("inf")
    # Quick spatial search: iterate all track nodes (small enough for London)
    slat, slon = st["lat"], st["lon"]
    for node in node_set:
        d = haversine(slat, slon, node[1], node[0])
        if d < best_dist:
            best_dist = d
            best_node = node
    if best_node and best_dist <= SNAP_RADIUS_M:
        station_snaps.append({
            "station_id": st["id"],
            "name": st["name"],
            "lat": st["lat"],
            "lon": st["lon"],
            "node": best_node,
            "snap_dist_m": int(best_dist)
        })
        # Add the station node to the graph, connected to the snapped track node
        st_key = f"STN_{st['id']}"
        G.add_node(st_key, is_station=True, name=st["name"], lat=st["lat"], lon=st["lon"])
        G.add_edge(st_key, best_node, weight=best_dist,
                   geometry=[[st["lon"], st["lat"]], [best_node[0], best_node[1]]])
    else:
        unmatched.append(st["name"])

print(f"Stations snapped: {len(station_snaps)}, unmatched: {len(unmatched)}")
if unmatched:
    print(f"  Unmatched: {unmatched[:10]}...")

# === Find station-to-station shortest paths ===
# We'll compute this on-demand in the router, not precompute all pairs.
# Export the graph structure (edges + station metadata) as JSON.

graph_export = {
    "stations": [{"id": s["station_id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"]}
                 for s in station_snaps],
    "edges": []  # edges between stations and track nodes
}

# Export track edges
for u, v, data in G.edges(data=True):
    geom = data.get("geometry")
    graph_export["edges"].append({
        "from": u, "to": v, "weight": data["weight"], "geometry": geom
    })

with open(OUT_FILE, "w") as f:
    json.dump(graph_export, f)

print(f"\nWritten {OUT_FILE}")
print(f"  stations: {len(graph_export['stations'])}")
print(f"  edges: {len(graph_export['edges'])}")
