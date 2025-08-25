import pickle
import json
from heapq import heappush, nlargest
import random
import requests
from datetime import datetime
import os
from dotenv import load_dotenv
from typing import Tuple, Dict, Any, List
from networkx import shortest_path
from shapely.geometry import LineString, mapping

# ---- Chargement des données ----
load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_API_KEY")  
stops_path = "data/output/stop_node_mapping.json"
graph_path = "data/output/hiking_graph.gpickle"
city_hubs_path = "data/output/city_hubs.json"

with open(stops_path, "r", encoding="utf-8") as f:
    stops_data = json.load(f)
with open(graph_path, "rb") as f:
    G = pickle.load(f)
with open(city_hubs_path, "r", encoding="utf-8") as f:
    city_hubs = json.load(f)

# ---- Calcul du point de départ ----


def get_best_transit_route(randomness=0.3, city="Lyon", departure_time: datetime = None):
    """
    Sélectionne le meilleur arrêt selon le score et récupère un itinéraire de transport en commun via Google Maps.
    """
    # --- Calculer le score pour chaque arrêt ---
    scored_stops = []
    for stop_id, stop_info in stops_data.items():
        props = stop_info.get("properties", {})
        score = (
            0.4 * (1 - props.get("duration_min_go_normalized", 0))
            + 0.5 * props.get("elevation_normalized", 0)
            + 0.1 * props.get("distance_to_pnr_border_normalized", 0)
        )
        # Ajouter la partie aléatoire
        rand_factor = random.random()
        score_final = (1 - randomness) * score + randomness * rand_factor
        scored_stops.append((score_final, stop_id, stop_info))

    # Trier par score décroissant
    scored_stops.sort(reverse=True, key=lambda x: x[0])    

    if city not in city_hubs:
        raise ValueError(f"Ville {city} non trouvée dans city_hubs.json")

    origin_coords = city_hubs[city]["coords"]
    origin = {"latLng": {"latitude": origin_coords[0], "longitude": origin_coords[1]}}

    # --- Parcourir les meilleurs arrêts pour trouver un itinéraire valide ---
    for score_final, stop_id, stop_info in scored_stops[:10]:  # max 10 essais
        dest_coords = stop_info["node"]
        destination = {"latLng": {"latitude": dest_coords[1], "longitude": dest_coords[0]}}
        body = {
            "origin": {"location": origin},
            "destination": {"location": destination},
            "travelMode": "TRANSIT",
            "departureTime": departure_time.astimezone().isoformat(),
            "transitPreferences": {"routingPreference": "FEWER_TRANSFERS"}
        }

        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": "*",
        }

        try:
            r = requests.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
            # Vérifier si un itinéraire a été trouvé
            if "routes" in data and len(data["routes"]) > 0:
                return data  # succès
        except Exception as e:
            print(f"⚠️ Tentative échouée pour l'arrêt {stop_id} ({score_final:.3f}): {e}")
            continue

    raise RuntimeError("Aucun itinéraire de transport en commun trouvé pour les 10 meilleurs arrêts.")

# ---- Calcul du nombre de kilomètres potentiels ----
def compute_max_hiking_distance(departure_time: datetime,
                                return_time: datetime,
                                level: str,
                                transit_route: Dict) -> float:
    """
    Calcule la distance maximale de randonnée possible en fonction du niveau,
    des jours, et des temps de transport aller-retour.

    Args:
        departure_time: datetime de départ.
        return_time: datetime de retour.
        level: niveau de randonnée ('debutant', 'intermediaire', 'avance', 'expert').
        transit_route: dictionnaire issu de get_best_transit_route.
    
    Returns:
        distance_max_m: distance maximale en mètres.
    """

    level_distance_map = {
        'debutant': 10_000,
        'intermediaire': 20_000,
        'avance': 30_000,
        'expert': 50_000
    }

    if level not in level_distance_map:
        raise ValueError(f"Niveau inconnu: {level}")

    dist_per_day = level_distance_map[level]
    
    # Nombre de jours (inclusif)
    nb_days = (return_time.date() - departure_time.date()).days + 1

    # --- Temps potentiel de marche par jour ---
    max_walk_seconds_per_day = 10 * 3600  # 10h par jour
    min_distance_day1 = 5_000  # minimum 5 km même si arrivée tardive
    distance_to_transit_stop = 1_000  # 1 km max pour rejoindre l'arrêt

    # Heure d'arrivée du transport pour le jour 1
    steps = transit_route["routes"][0]["legs"][0]["steps"]
    transit_steps = [s for s in steps if s["travelMode"] == "TRANSIT"]
    
    if transit_steps:
        last_transit = transit_steps[-1]
        arrival_str = last_transit["transitDetails"]["stopDetails"]["arrivalTime"]
        if arrival_str:
            transit_arrival_time = datetime.fromisoformat(arrival_str.replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            # Sinon on prend le return du step en WALK précédent la fin
            transit_arrival_time = departure_time
    else:
        transit_arrival_time = departure_time

    # Temps dispo le premier jour (proportionnel)
    seconds_available_first_day = max_walk_seconds_per_day - max(0, (transit_arrival_time - departure_time).total_seconds())
    fraction_day1 = max(0, seconds_available_first_day / max_walk_seconds_per_day)
    distance_day1 = max(min_distance_day1, dist_per_day * fraction_day1)

    # Temps dispo le dernier jour (jour de retour)
    distance_last_day = dist_per_day  # par défaut complet
    duration_str = transit_route["routes"][0]["legs"][0]["duration"]
    transit_seconds_return = int(duration_str.replace("s", ""))
    seconds_available_last_day = max(0, max_walk_seconds_per_day - transit_seconds_return)
    fraction_last_day = seconds_available_last_day / max_walk_seconds_per_day
    distance_last_day = dist_per_day * fraction_last_day

    # Distance totale maximale
    if nb_days == 1:
        distance_max_m = distance_day1
    else:
        # jour 1 + jours intermédiaires + dernier jour - distance pour rejoindre l'arrêt
        distance_max_m = distance_day1 + dist_per_day * (nb_days - 2) + distance_last_day - distance_to_transit_stop

    return distance_max_m

# ---- Calcul de l'itinéraire ----

def haversine(coord1, coord2):
    import math
    R = 6371000
    lat1, lon1 = map(math.radians, coord1)
    lat2, lon2 = map(math.radians, coord2)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def find_nearest_node(G, coord):
    return min(G.nodes, key=lambda n: haversine(coord, (n[1], n[0])))

def best_hiking_path(graph_path, start_coord, max_distance_m, k=50):
    """
    Cherche un chemin maximisant le score total sous la distance max,
    version optimisée pour grands graphes avec suppression des impasses.
    """

    start_node = find_nearest_node(G, start_coord)

    # Heap de candidats : (-score, distance, chemin)
    candidates = [(-0.0, 0.0, (start_node,))]
    best_path, best_score, best_dist = (start_node,), 0.0, 0.0

    while candidates:
        new_candidates = []
        for neg_score, dist, path in candidates:
            current = path[-1]
            for neighbor in G.neighbors(current):
                if neighbor in path:
                    continue
                edge_data = G[current][neighbor]
                if isinstance(edge_data, dict) and 0 in edge_data:
                    edge_data = edge_data[0]
                length = edge_data.get("length", 0.0)
                edge_score = edge_data.get("score", 0.0)
                new_dist = dist + length
                if new_dist > max_distance_m:
                    continue
                new_score = -neg_score + edge_score
                new_path = path + (neighbor,)
                heappush(new_candidates, (-new_score, new_dist, new_path))
                if new_score > best_score or (new_score == best_score and new_dist > best_dist):
                    best_path, best_score, best_dist = new_path, new_score, new_dist

        # Conserver uniquement les k meilleurs candidats
        candidates = nlargest(k, new_candidates, key=lambda x: -x[0])

    return best_path, best_score, best_dist, G

def save_geojson(data, output_path="data/paths/optimized_routes.geojson"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        print(f"✅ GeoJSON sauvegardé dans {output_path}")

# ---- Calcul du retour en transport en commun ----
def compute_return_transit(path, return_time: datetime, city: str):
    """
    Calcule le trajet retour en transport en commun depuis le dernier point du path jusqu'à la ville.
    Ajoute également la marche jusqu'au premier arrêt de TC dans le path.

    Args:
        path: liste de coordonnées [(lon, lat), ...] issue de best_hiking_path
        return_time: datetime du départ pour le retour
        city: nom de la ville de destination
        graph_path: chemin vers le graphe de randonnée
        stops_path: chemin vers le fichier des arrêts
        max_attempts: nombre d'arrêts à tester si pas de trajet

    Returns:
        augmented_path: path initial + marche jusqu'au départ du TC
        return_transit_route: réponse complète de l'API Google
    """
    if isinstance(path, tuple):
        path = list(path)

    last_point = path[-1]  # (lon, lat)

    # --- Trier les arrêts par distance au dernier point ---
    stops_list = []
    for stop_id, stop in stops_data.items():
        stop_coord = tuple(stop["node"])  # [lon, lat]
        dist = haversine((last_point[1], last_point[0]), (stop_coord[1], stop_coord[0])) 
        stops_list.append((dist, stop_id, stop_coord))
    stops_list.sort(key=lambda x: x[0])

    return_transit_route = None
    first_step_start = None

    # --- Tester les stops jusqu'à trouver un itinéraire TC ---
    for _, stop_id, stop_coord in stops_list[:10]:
        origin = {"location": {"latLng": {"latitude": stop_coord[1], "longitude": stop_coord[0]}}}
        # Destination city : on peut récupérer coords depuis un dictionnaire city_hubs      
        city_coords = city_hubs[city]["coords"]
        destination = {"location": {"latLng": {"latitude": city_coords[0], "longitude": city_coords[1]}}}

        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": "*",
        }
        body = {
            "origin": origin,
            "destination": destination,
            "travelMode": "TRANSIT",
            "departureTime": return_time.astimezone().isoformat(),
            "transitPreferences": {"routingPreference": "FEWER_TRANSFERS"}
        }

        r = requests.post(url, headers=headers, json=body)
        if r.status_code == 200:
            resp = r.json()
            steps = resp.get("routes", [{}])[0].get("legs", [{}])[0].get("steps", [])
            transit_steps = [s for s in steps if s["travelMode"] == "TRANSIT"]
            if transit_steps:
                return_transit_route = resp
                first_step_start = transit_steps[0]["startLocation"]["latLng"]
                break

    if return_transit_route is None:
        raise RuntimeError("Impossible de trouver un itinéraire retour en transport en commun.")

    # --- Ajouter la marche jusqu'au premier step TC ---
    # Convertir shortest_path du graphe de randonnée entre dernier point du path et premier step TC
    start_coord = (last_point[1], last_point[0])  # (lat, lon)
    end_coord = (first_step_start["latitude"], first_step_start["longitude"])

    start_node = find_nearest_node(G, start_coord)
    end_node = find_nearest_node(G, end_coord)

    if start_node is None or end_node is None:
        raise RuntimeError("Impossible de trouver les noeuds du graphe pour la marche finale.")

    sp_nodes = shortest_path(G, source=start_node, target=end_node, weight="length")

    augmented_path = path + sp_nodes

    return augmented_path, return_transit_route

# ---- Fonction principale combinée ----
def compute_best_route(randomness=0.2, city="Lyon", departure_time: datetime = None, return_time: datetime = None, level: str = "intermediaire"):
    """
    Planifie une randonnée en utilisant le meilleur itinéraire en transport .replace(tzinfo=None)en commun pour atteindre le départ.
    """
    departure_time = datetime.fromisoformat(departure_time)
    return_time = datetime.fromisoformat(return_time)
    # --- Étape 1 : Récupérer l'itinéraire de transport en commun ---
    travel_go = get_best_transit_route(randomness=randomness, city=city, departure_time=departure_time)
    # --- Étape 2 : Extraire les coordonnées du dernier point de transit ---
    transit_end = None
    if travel_go:
        steps = travel_go["routes"][0]["legs"][0]["steps"]
        transit_steps = [s for s in steps if s["travelMode"] == "TRANSIT"]
        if transit_steps:
            last_transit = transit_steps[-1]
            end_lat = last_transit["endLocation"]["latLng"]["latitude"]
            end_lon = last_transit["endLocation"]["latLng"]["longitude"]
            transit_end = (end_lon, end_lat)  # (lon, lat)
    if transit_end is None:
        raise RuntimeError("Impossible de déterminer le point de départ de la randonnée depuis l'itinéraire TC.")
    # --- Étape 3 : Calculer la distance maximale de randonnée ---
    max_distance_m = compute_max_hiking_distance(departure_time, return_time, level, travel_go)
    # --- Étape 4 : Lancer la recherche du meilleur chemin de randonnée ---
    path, score, dist, G = best_hiking_path(graph_path, start_coord=(transit_end[1], transit_end[0]), max_distance_m=max_distance_m, k=50)
    # --- Étape 5 : Calculer l'itinéraire retour en transport en commun ---
    path, travel_return = compute_return_transit(path, return_time, city)
    # --- Étape 6 : Construire la Feature GeoJSON ---
    start_coord = path[0]
    end_coord = path[-1]

    feature = {
        "type": "Feature",
        "geometry": mapping(LineString(path)),
        "properties": {
            "start_coord": start_coord,
            "end_coord": end_coord,
            "path_score": score,
            "path_length": dist,
            "transit_go": travel_go,
            "transit_back": travel_return
        }
    }

    return {
        "type": "FeatureCollection",
        "features": [feature]
    }

if __name__ == "__main__":
    # Exemple de paramètres
    randomness = 0.3
    city = "Lyon"
    departure_time = datetime(2025, 8, 26, 8, 0)   # Départ 8h
    return_time = datetime(2025, 8, 26, 20, 0)     # Retour 20h
    level = "intermediaire"
    k = 50
    graph_path = "data/output/hiking_graph.gpickle"

    try:
        result = compute_best_route(
            randomness=randomness,
            city=city,
            departure_time=departure_time,
            return_time=return_time,
            level=level,
            k=k,
            graph_path=graph_path
        )

        print("=== Résultat ===")
        print(f"Distance randonnée : {result['hiking_distance']} m")
        print(f"Score randonnée : {result['hiking_score']}")
        print(f"Nombre d'étapes (noeuds) : {len(result['hiking_path'])}")
        print("Coordonnées départ randonnée :", result['hiking_path'][0] if result['hiking_path'] else "N/A")

    except Exception as e:
        print("❌ Erreur pendant le test :", e)
