import geopandas as gpd
import pandas as pd
import networkx as nx
import pickle
from shapely.geometry import Point, LineString
from scipy.spatial import KDTree
import numpy as np
import json
import os
from shapely.ops import transform
from pyproj import Geod

# === Chargement des fichiers ===

paths_fp = "data/output/chartreuse_hiking_paths_with_poi_scores.geojson"
stops_fp = "data/output/chartreuse_scores_final.geojson"

paths = gpd.read_file(paths_fp)
stops = gpd.read_file(stops_fp)

# === Construction du graphe ===

geod = Geod(ellps="WGS84")

G = nx.Graph()

def segment_length_m(p1, p2):
    """Calcule la distance en mètres entre deux points (lon, lat)"""
    _, _, distance = geod.inv(p1[0], p1[1], p2[0], p2[1])
    return distance

MAX_SEGMENT_LENGTH = 1000  # mètres

for idx, feature in paths.iterrows():
    coords = list(feature.geometry.coords)
    total_score = feature.get("score_total_normalized", 0.0)
    total_length = feature.get("distance_meters", 0.0)

    if total_length == 0 or len(coords) < 2:
        continue

    for i in range(len(coords) - 1):
        pt1 = tuple(coords[i])
        pt2 = tuple(coords[i + 1])

        length = segment_length_m(pt1, pt2)

        if length == 0 or length > MAX_SEGMENT_LENGTH:
            continue  # on ignore les artefacts

        # Proportion du score pour ce segment
        score = total_score 

        if G.has_edge(pt1, pt2):
            # On conserve le score le plus élevé
            if G[pt1][pt2]['score'] < score:
                G[pt1][pt2].update({'score': score, 'length': length})
        else:
            G.add_edge(pt1, pt2, score=score, length=length)

print(f"✅ Graphe proprement construit : {G.number_of_nodes()} nœuds, {G.number_of_edges()} arêtes.")

# === Association des arrêts de transport aux nœuds du graphe avec KDTree ===

graph_nodes = list(G.nodes)
node_coords = np.array(graph_nodes)  # format : [[lon, lat], ...]

# Création de l’arbre KDTree
tree = KDTree(node_coords)

stop_nodes = {}
for idx, stop in stops.iterrows():
    stop_point = stop.geometry
    stop_coord = (stop_point.x, stop_point.y)
    
    dist, nearest_idx = tree.query(stop_coord)
    nearest_node = tuple(node_coords[nearest_idx])

    stop_nodes[idx] = {
        'node': nearest_node,
        'properties': stop.drop(labels='geometry').to_dict()
    }

print(f"✅ {len(stop_nodes)} arrêts associés à un nœud du graphe (via KDTree).")

# === Sauvegarde des résultats ===

output_dir = "data/output"
os.makedirs(output_dir, exist_ok=True)

graph_path = os.path.join(output_dir, "hiking_graph.gpickle")
stops_path = os.path.join(output_dir, "stop_node_mapping.json")

with open(graph_path, "wb") as f:
    pickle.dump(G, f)
    
with open(stops_path, "w") as f:
    json.dump(stop_nodes, f)

print(f"✅ Graphe sauvegardé dans : {graph_path}")
print(f"✅ Correspondance arrêts-nœuds sauvegardée dans : {stops_path}")