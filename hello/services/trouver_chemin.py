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

def is_valid_transit(result):
    """Vérifie si le résultat contient bien des itinéraires de transport en commun"""
    if not result or not isinstance(result, dict):
        return False
    # Vérifier si 'routes' existe et contient quelque chose
    return "routes" in result and len(result["routes"]) > 0

import networkx as nx
from shapely.geometry import LineString, mapping

def extend_linestring_with_transit(best_feature, G, edge_cost="edge_cost"):
    """
    Étend le LineString du meilleur chemin avec les tronçons piétons
    reliant le transport en commun (Google Routes) au graphe piéton.
    
    - Ajoute au début : chemin entre arrêt de descente (dernier step TRANSIT du 'travel_go')
      et le début du LineString
    - Ajoute à la fin : chemin entre arrêt de montée (premier step TRANSIT du 'travel_back')
      et la fin du LineString
    """
    
    coords = list(best_feature["geometry"]["coordinates"])

    # ---- 1. Aller : compléter le début ----
    travel_go = best_feature["properties"].get("transit_go")
    if travel_go:
        steps = travel_go["routes"][0]["legs"][0]["steps"]
        # on récupère le dernier step en TRANSIT
        transit_steps = [s for s in steps if s["travelMode"] == "TRANSIT"]
        if transit_steps:
            last_transit = transit_steps[-1]
            end_lat = last_transit["endLocation"]["latLng"]["latitude"]
            end_lon = last_transit["endLocation"]["latLng"]["longitude"]
            transit_end = (end_lon, end_lat)  # (lon, lat)

            # début du chemin piéton
            start_ls = tuple(coords[0])
            print(transit_end in G, start_ls in G)
            if transit_end not in G:
                transit_end = min(G.nodes, key=lambda n: (n[0]-transit_end[0])**2 + (n[1]-transit_end[1])**2)

            if start_ls not in G:
                start_ls = min(G.nodes, key=lambda n: (n[0]-start_ls[0])**2 + (n[1]-start_ls[1])**2)
            print(transit_end in G, start_ls in G)

            try:
                # shortest path dans G
                path = nx.shortest_path(G, source=transit_end, target=start_ls, weight=edge_cost)
                # on ajoute ce chemin au début
                coords = path + coords
            except nx.NetworkXNoPath:
                pass

    # ---- 2. Retour : compléter la fin ----
    travel_back = best_feature["properties"].get("transit_back")
    if travel_back:
        steps = travel_back["routes"][0]["legs"][0]["steps"]
        # on récupère le premier step en TRANSIT
        transit_steps = [s for s in steps if s["travelMode"] == "TRANSIT"]
        if transit_steps:
            first_transit = transit_steps[0]
            start_lat = first_transit["startLocation"]["latLng"]["latitude"]
            start_lon = first_transit["startLocation"]["latLng"]["longitude"]
            transit_start = (start_lon, start_lat)

            # fin du chemin piéton
            end_ls = tuple(coords[-1])

            if transit_start not in G:
                transit_start = min(G.nodes, key=lambda n: (n[0]-transit_start[0])**2 + (n[1]-transit_start[1])**2)

            if end_ls not in G:
                end_ls = min(G.nodes, key=lambda n: (n[0]-end_ls[0])**2 + (n[1]-end_ls[1])**2)
            try:
                # shortest path dans G
                path = nx.shortest_path(G, source=end_ls, target=transit_start, weight=edge_cost)
                # on ajoute ce chemin à la fin (sans répéter le 1er point du path)
                coords = coords + path[1:]
            except nx.NetworkXNoPath:
                pass

    # ---- mise à jour du LineString ----
    linestring = LineString(coords)
    best_feature["geometry"] = mapping(linestring)

    # ---- recalcul de la longueur totale ----
    path_length = linestring.length
    best_feature["properties"]["path_length"] = path_length

    return best_feature



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

    top_depart = select_top_with_randomness(stop_nodes, "depart_score", top_n=8, randomness=randomness)
    top_arrival = select_top_with_randomness(stop_nodes, "arrival_score", top_n=8, randomness=randomness)
    
    def edge_cost(u, v, d):
        return d["length"] / (d.get("score", 0) + 1e-6)

    # Boucle principale de recherche
    best_feature = None
    best_score = float('-inf')
    itineraires = []

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

            total_score = 100*start["depart_score"] + 100*end["arrival_score"] + path_score

            if path_length == 0 or path_length > max_distance_m:
                continue

            feature = {
                "type": "Feature",
                "geometry": mapping(LineString(path)),
                "properties": {
                    "start_id": start_id,
                    "start_coord": start_coord,
                    "end_coord": end_coord,
                    "end_id": end_id,
                    "depart_score": start["depart_score"],
                    "arrival_score": end["arrival_score"],
                    "path_score": path_score,
                    "path_length": path_length,
                    "total_score": total_score
                }
            }
            itineraires.append(feature)
    itineraires = sorted(itineraires, key=lambda x: x["properties"]["total_score"], reverse=True)

    transit_go = None
    transit_back = None
    i = 0
    if departure_datetime:
            dep_dt = datetime.fromisoformat(departure_datetime)  # ex: "2025-08-20T08:30"
    if return_datetime:
        ret_dt = datetime.fromisoformat(return_datetime)
    origin_coords = city_hubs[city]["coords"]  # [lat, lon]

    while (transit_go is None or transit_back is None) and i < len(itineraires):
        # Aller
        origin = {"latitude": origin_coords[0], "longitude": origin_coords[1]}
        destination = {
            "latitude": itineraires[i]["properties"]["start_coord"][1],
            "longitude": itineraires[i]["properties"]["start_coord"][0]
        }
        result_go = get_transit_directions(origin, destination, dep_dt)
        if is_valid_transit(result_go):
            transit_go = result_go
            # Retour
            origin = {
                "latitude": itineraires[i]["properties"]["end_coord"][1],
                "longitude": itineraires[i]["properties"]["end_coord"][0]
            }
            destination = {"latitude": origin_coords[0], "longitude": origin_coords[1]}
            result_back = get_transit_directions(origin, destination, ret_dt)
            if is_valid_transit(result_back):
                transit_back = result_back
        i += 1

    if transit_go is None or transit_back is None:
        print("Aucun itinéraire de transport en commun trouvé.")
        return {"type": "FeatureCollection", "features": []}

    best_feature = itineraires[i-1]  # -1 car i a été incrémenté
    best_feature["properties"]["transit_go"] = transit_go
    best_feature["properties"]["transit_back"] = transit_back

    best_feature = extend_linestring_with_transit(best_feature, G, edge_cost)
    return {
        "type": "FeatureCollection",
        "features": [best_feature]
    }


def save_geojson(data, output_path="data/paths/optimized_routes.geojson"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    geojson = compute_best_route(level='intermediaire', departure_datetime="2025-08-20T08:30", return_datetime="2025-08-20T19:00")
    save_geojson(geojson)
