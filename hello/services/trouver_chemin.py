import networkx as nx
import json
from shapely.geometry import LineString, mapping
from scipy.spatial.distance import euclidean
import pickle
import os
from dotenv import load_dotenv
import time
import numpy as np
from datetime import datetime
import requests

load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_API_KEY")  

def get_transit_directions(origin, destination, departure_time):
    """Appelle l’API Google Directions pour un itinéraire en transport en commun."""
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "*",
    }
    body = {
        "origin": {"location": {"latLng": origin}},
        "destination": {"location": {"latLng": destination}},
        "travelMode": "TRANSIT",
        "departureTime": departure_time.astimezone().isoformat(),
        "transitPreferences": {
            "routingPreference": "FEWER_TRANSFERS"
        }
    }
    r = requests.post(url, headers=headers, json=body)
    data = r.json()
    return data

def compute_best_route(level: str = 'intermediaire', city: str = 'Lyon', massif: str = 'Chartreuse', randomness: float = 0.3, departure_datetime: str | None = None, return_datetime: str | None = None):    
    """
    Calcule la meilleure route optimisée selon le niveau,
    et retourne un dict GeoJSON avec UNE seule Feature, la meilleure.
    city et massif sont pour l'instant ignorés mais gardés en argument.
    """
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
    city_hubs_path = "data/output/city_hubs.json"

    t_load_start = time.perf_counter()
    with open(graph_path, "rb") as f:
        G = pickle.load(f)
    with open(stops_path, "r") as f:
        stop_nodes = json.load(f)
    with open(city_hubs_path, "r") as f:
        city_hubs = json.load(f)

    # Calcul des scores
    def compute_depart_score(props):
        return (
            0.4 * (1 - props["duration_min_go_normalized"]) +
            0.5 * props["elevation_normalized"] +
            0.1 * props["distance_to_pnr_border_normalized"]
        )

    def compute_arrival_score(props):
        return (
            0.4 * (1 - props["duration_min_back_normalized"]) +
            0.5 * props["elevation_normalized"] +
            0.1 * props["distance_to_pnr_border_normalized"]
        )

    for stop_id, stop in stop_nodes.items():
        props = stop["properties"]
        stop["depart_score"] = compute_depart_score(props)
        stop["arrival_score"] = compute_arrival_score(props)
        stop["coord"] = tuple(stop["node"])
    
    # Tri top départs / arrivées avec aléatoire

    def normalize_scores(items, score_key):
        scores = np.array([item[1][score_key] for item in items])
        min_s, max_s = scores.min(), scores.max()
        if max_s - min_s == 0:
            return np.ones_like(scores)
        return (scores - min_s) / (max_s - min_s)

    def select_top_with_randomness(stop_nodes, score_key, top_n=10, randomness=0.3):
        items = list(stop_nodes.items())
        normalized_scores = normalize_scores(items, score_key)
        
        # Calcul du score mixte (pondération score + aléatoire)
        mixed_scores = (1 - randomness) * normalized_scores + randomness * np.random.rand(len(items))
        
        # Tri selon ce score mixte décroissant
        sorted_items = [item for _, item in sorted(zip(mixed_scores, items), key=lambda x: x[0], reverse=True)]
        
        # Prendre les top_n
        selected = sorted_items[:top_n]
        
        return selected

    top_depart = select_top_with_randomness(stop_nodes, "depart_score", top_n=5, randomness=randomness)
    top_arrival = select_top_with_randomness(stop_nodes, "arrival_score", top_n=5, randomness=randomness)

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


    if best_feature is None:
        return {
            "type": "FeatureCollection",
            "features": []
        }
    
    # Récupérer start_id et end_id depuis best_feature
    start_id = str(best_feature["properties"]["start_id"])
    end_id = str(best_feature["properties"]["end_id"])

    # Coordonnées des stops
    start_coords = stop_nodes[start_id]["node"]  # [lon, lat]
    end_coords = stop_nodes[end_id]["node"]      # [lon, lat]

    # Aller → city vers stop de départ
    if departure_datetime:
        dep_dt = datetime.fromisoformat(departure_datetime)  # ex: "2025-08-20T08:30"
        origin_coords = city_hubs[city]["coords"]  # [lat, lon]
        origin = {"latitude": origin_coords[0], "longitude": origin_coords[1]}
        destination = {"latitude": start_coords[1], "longitude": start_coords[0]}
        print(origin, destination, dep_dt)
        best_feature["properties"]["transit_go"] = get_transit_directions(origin, destination, dep_dt)

    # Retour → stop d’arrivée vers city
    if return_datetime:
        ret_dt = datetime.fromisoformat(return_datetime)
        origin = {"latitude": end_coords[1], "longitude": end_coords[0]}
        destination = {"latitude": origin_coords[0], "longitude": origin_coords[1]}
        print(origin, destination, ret_dt)
        best_feature["properties"]["transit_back"] = get_transit_directions(origin, destination, ret_dt)
    return {
        "type": "FeatureCollection",
        "features": [best_feature]
    }


def save_geojson(data, output_path="data/paths/optimized_routes.geojson"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    geojson = compute_best_route(level='debutant', departure_datetime="2025-08-18T08:30", return_datetime="2025-08-18T19:00")
    save_geojson(geojson)
