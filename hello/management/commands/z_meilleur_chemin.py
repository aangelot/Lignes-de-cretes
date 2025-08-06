import networkx as nx
import json
import numpy as np
from shapely.geometry import LineString, mapping
from scipy.spatial.distance import euclidean
import pickle
import os
import random

# === Chargement des données ===

graph_path = "data/output/hiking_graph.gpickle"
stops_path = "data/output/stop_node_mapping.json"

with open(graph_path, "rb") as f:
    G = pickle.load(f)

with open(stops_path, "r") as f:
    stop_nodes = json.load(f)

# === Calcul des scores départ / arrivée ===

def compute_depart_score(props):
    return (
        0.5 * (1 - props["duration_min_go_normalized"]) +
        0.3 * props["elevation_normalized"] +
        0.2 * props["distance_to_pnr_border_normalized"]
    )

def compute_arrival_score(props):
    return (
        0.5 * (1 - props["duration_min_back_normalized"]) +
        0.3 * props["elevation_normalized"] +
        0.2 * props["distance_to_pnr_border_normalized"]
    )

for stop_id, stop in stop_nodes.items():
    props = stop["properties"]
    stop["depart_score"] = compute_depart_score(props)
    stop["arrival_score"] = compute_arrival_score(props)
    stop["coord"] = tuple(stop["node"])

# === Sélection des meilleurs points ===

top_depart = sorted(stop_nodes.items(), key=lambda x: x[1]["depart_score"], reverse=True)[:15]
top_arrival = sorted(stop_nodes.items(), key=lambda x: x[1]["arrival_score"], reverse=True)[:15]


# === Fonction de coût de l'arête ===

def edge_cost(u, v, d):
    return d["length"] / (d.get("score", 0) + 1e-6)

# === Recherche des itinéraires ===

max_distance_m = 15000  # 15 km

features = []

for start_id, start in top_depart:
    start_coord = start["coord"]
    for end_id, end in top_arrival:
        end_coord = end["coord"]

        if start_id == end_id:
            continue

        dist_euclid_m = euclidean(start_coord, end_coord) * 111000  # Approx. degrés -> mètres
        if dist_euclid_m > max_distance_m:
            continue

        try:
            path = nx.shortest_path(G, source=start_coord, target=end_coord, weight=edge_cost)
        except nx.NetworkXNoPath:
            continue

        # Score du chemin
        path_score = 0
        path_length = 0
        for i in range(len(path) - 1):
            edge_data = G.get_edge_data(path[i], path[i+1])
            path_score += edge_data.get("score", 0)
            path_length += edge_data.get("length", 0)
        total_score = start["depart_score"] + end["arrival_score"] + path_score
        for i in range(len(path) - 1):
            u = path[i]
            v = path[i + 1]
        
        if path_length == 0 or path_length > max_distance_m:
            continue
        print(f"Path from {start_id} to {end_id}: score={total_score:.3f}, length={path_length:.1f} m")

        feature = {
            "type": "Feature",
            "geometry": mapping(LineString(path)),
            "properties": {
                "start_id": start_id,
                "end_id": end_id,
                "depart_score": start["depart_score"],
                "arrival_score": end["arrival_score"],
                "path_score": path_score,
                "path_length": path_length,
                "total_score": total_score
            }
        }

        features.append(feature)

# === Sauvegarde GeoJSON ===

output_geojson = {
    "type": "FeatureCollection",
    "features": features
}

output_path = "data/paths/optimized_routes.geojson"
os.makedirs(os.path.dirname(output_path), exist_ok=True)

with open(output_path, "w") as f:
    json.dump(output_geojson, f, indent=2)

print(f"✅ {len(features)} itinéraires optimisés sauvegardés dans : {output_path}")
