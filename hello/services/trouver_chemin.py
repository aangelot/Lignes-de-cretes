import networkx as nx
import json
from shapely.geometry import LineString, mapping
from scipy.spatial.distance import euclidean
import pickle
import os
import time

def compute_best_route(level='intermediaire', city='Lyon', massif='Chartreuse'):
    """
    Calcule la meilleure route optimisée selon le niveau,
    et retourne un dict GeoJSON avec UNE seule Feature, la meilleure.
    city et massif sont pour l'instant ignorés mais gardés en argument.
    """

    t0 = time.perf_counter()

    level_distance_map = {
        'debutant': 10_000,
        'intermediaire': 20_000,
        'avance': 30_000,
        'expert': 50_000
    }
    max_distance_m = level_distance_map.get(level, 15_000)

    # Chargement des données
    graph_path = "data/output/hiking_graph.gpickle"
    stops_path = "data/output/stop_node_mapping.json"

    t_load_start = time.perf_counter()
    with open(graph_path, "rb") as f:
        G = pickle.load(f)
    with open(stops_path, "r") as f:
        stop_nodes = json.load(f)
    t_load_end = time.perf_counter()
    print(f"[compute_best_route] Chargement données : {t_load_end - t_load_start:.3f} sec")

    # Calcul des scores
    t_score_start = time.perf_counter()
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
    t_score_end = time.perf_counter()
    print(f"[compute_best_route] Calcul des scores : {t_score_end - t_score_start:.3f} sec")

    # Tri top départs / arrivées
    t_sort_start = time.perf_counter()
    top_depart = sorted(stop_nodes.items(), key=lambda x: x[1]["depart_score"], reverse=True)[:10]
    top_arrival = sorted(stop_nodes.items(), key=lambda x: x[1]["arrival_score"], reverse=True)[:10]
    t_sort_end = time.perf_counter()
    print(f"[compute_best_route] Tri top départs/arrivées : {t_sort_end - t_sort_start:.3f} sec")

    # Fonction pour filtrer points trop proches (< 500m) en ne gardant que celui avec meilleur score
    def filter_points(points, score_key):
        filtered = []
        for stop_id, stop in points:
            coord = stop["coord"]
            too_close = False
            for _, fstop in filtered:
                dist = euclidean(coord, fstop["coord"]) * 111000
                if dist < 500:  # seuil 500m
                    too_close = True
                    break
            if not too_close:
                filtered.append((stop_id, stop))
        return filtered

    top_depart = filter_points(top_depart, "depart_score")
    top_arrival = filter_points(top_arrival, "arrival_score")
    
    def edge_cost(u, v, d):
        return d["length"] / (d.get("score", 0) + 1e-6)

    # Boucle principale de recherche
    t_loop_start = time.perf_counter()
    best_feature = None
    best_score = float('-inf')

    for start_id, start in top_depart:
        start_coord = start["coord"]
        for end_id, end in top_arrival:
            end_coord = end["coord"]

            if start_id == end_id:
                continue

            dist_euclid_m = euclidean(start_coord, end_coord) * 111000
            if dist_euclid_m > max_distance_m or dist_euclid_m < 3000: # Minimum 3 km
                continue

            try:
                path = nx.shortest_path(G, source=start_coord, target=end_coord, weight=edge_cost)
            except nx.NetworkXNoPath:
                continue

            path_score = 0
            path_length = 0
            for i in range(len(path) - 1):
                edge_data = G.get_edge_data(path[i], path[i + 1])
                path_score += edge_data.get("score", 0)
                path_length += edge_data.get("length", 0)

            total_score = start["depart_score"] + end["arrival_score"] + path_score

            if path_length == 0 or path_length > max_distance_m:
                continue

            if total_score > best_score:
                best_score = total_score
                best_feature = {
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
    t_loop_end = time.perf_counter()
    print(f"[compute_best_route] Boucle de recherche : {t_loop_end - t_loop_start:.3f} sec")

    # Temps total
    print(f"[compute_best_route] Temps total : {t_loop_end - t0:.3f} sec")

    if best_feature is None:
        return {
            "type": "FeatureCollection",
            "features": []
        }

    return {
        "type": "FeatureCollection",
        "features": [best_feature]
    }


def save_geojson(data, output_path="data/paths/optimized_routes.geojson"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    print("Test de compute_best_route() avec niveau 'debutant'...")
    geojson = compute_best_route(level='expert')
    save_geojson(geojson)
    print("✅ Fichier GeoJSON généré dans data/paths/optimized_routes.geojson")