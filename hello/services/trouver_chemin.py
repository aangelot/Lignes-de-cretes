"""
Orchestration principale pour la planification de randonnées.
Coordonne les étapes aller/retour, calculs d'altitude et extraction des POI proches.
"""

import json
import os
import pickle
from datetime import datetime
from shapely.geometry import LineString, mapping
from django.conf import settings
from hello.management.commands.utils import slugify

# Imports des modules spécialisés
from .geotools import save_geojson_gpx
from .transit import get_best_transit_route, compute_max_hiking_distance, compute_return_transit
from .hiking import best_hiking_path, extract_pois_near_path
from .elevation import get_elevations, smooth_elevations, compute_total_ascent


def compute_best_route(
    randomness=0.2,
    city="Lyon",
    massif="Chartreuse",
    departure_time: datetime = None,
    return_time: datetime = None,
    level: str = "intermediaire",
    address: str = "",
    transit_priority: str = "balanced",
):
    """
    Planifie une randonnée en utilisant le meilleur itinéraire en transport en commun pour atteindre le départ.
    
    Étapes :
    1. Récupère l'itinéraire de transport en commun (aller)
    2. Calcule la distance maximale de randonnée disponible
    3. Trouve le meilleur chemin de randonnée via POI
    4. Planifie le retour en transport en commun
    5. Récupère les altitudes et calcule le dénivelé
    6. Extrait les POI à proximité du tracé
    7. Retourne un GeoJSON avec tous les détails
    """

    massif_clean = slugify(massif)
    city_clean = slugify(city)

    stops_path = f"data/output/{massif_clean}_{city_clean}_stop_node_mapping.json"
    graph_path = f"data/output/{massif_clean}_hiking_graph.gpickle"
    poi_file = f"data/output/{massif_clean}_poi_scores.geojson"
    gares_path = "data/input/gares_departs.json"

    for path in [stops_path, graph_path, gares_path, poi_file]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"❌ Fichier introuvable pour le massif {massif} : {path}")
        
    # Chargement des données
    with open(stops_path, "r", encoding="utf-8") as f:
        stops_data = json.load(f)

    with open(graph_path, "rb") as f:
        G = pickle.load(f)

    with open(gares_path, "r", encoding="utf-8") as f:
        gares = json.load(f)

    with open(poi_file, "r", encoding="utf-8") as f:
        poi_data = json.load(f)

    if getattr(settings, "USE_MOCK_DATA", False):
        file_path = os.path.join(settings.BASE_DIR, "hello/static/hello/data/optimized_routes_example.geojson")
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
        
    departure_time = datetime.fromisoformat(departure_time)
    return_time = datetime.fromisoformat(return_time)
    for stop_id, stop_info in stops_data.items():
        stop_info.setdefault("failure_count", 0)

    # --- Étape 1 : Récupérer l'itinéraire de transport en commun ---
    travel_go = get_best_transit_route(
        randomness=randomness, city=city, departure_time=departure_time, 
        return_time=return_time, stops_data=stops_data, gares=gares, 
        address=address, transit_priority=transit_priority
    )
    
    # --- Étape 2 : Extraire les coordonnées du dernier point de transit ---
    transit_end = None
    if travel_go:
        steps = travel_go["routes"][0]["legs"][0]["steps"]
        transit_steps = [s for s in steps if s["travelMode"] == "TRANSIT"]
        if transit_steps:
            last_transit = transit_steps[-1]
            end_lat = last_transit["endLocation"]["latLng"]["latitude"]
            end_lon = last_transit["endLocation"]["latLng"]["longitude"]
            transit_end = (end_lon, end_lat)
    if transit_end is None:
        raise RuntimeError("Impossible de déterminer le point de départ de la randonnée depuis l'itinéraire TC.")
    
    # --- Étape 3 : Calculer la distance maximale de randonnée ---
    max_distance_m = compute_max_hiking_distance(departure_time, return_time, level, travel_go)
    print(f"Distance maximale de randonnée estimée : {max_distance_m/1000:.1f} km")
    
    # --- Étape 4 : Lancer la recherche du meilleur chemin de randonnée ---
    path, dist = best_hiking_path(
        start_coord=(transit_end[0], transit_end[1]), max_distance_m=max_distance_m, 
        G=G, poi_data=poi_data, randomness=randomness
    )
    print(f"Distance de randonnée planifiée : {dist/1000:.1f} km")
    
    # --- Étape 5 : Calculer l'itinéraire retour en transport en commun ---
    path, travel_return, dist = compute_return_transit(
        path, return_time, city, G=G, stops_data=stops_data, gares=gares, address=address
    )
    print(f"Distance totale avec retour en TC : {dist/1000:.1f} km")
    
    # --- Étape 5b : Récupérer les élévations ---
    elevations = get_elevations(path)
    smoothed_elevations = smooth_elevations(elevations, window=10)
    total_ascent = compute_total_ascent(smoothed_elevations)

    # Ajouter les élévations au chemin
    path = [
        [lon, lat, round(ele)] for (lon, lat), ele in zip(path, smoothed_elevations)
    ]

    # Sauvegarde des arrêts inaccessibles
    with open(stops_path, "w", encoding="utf-8") as f:
        json.dump(stops_data, f, indent=2, ensure_ascii=False)

    # --- Étape 6 : Construire la Feature GeoJSON ---
    start_coord = path[0]
    end_coord = path[-1]

    feature = {
        "type": "Feature",
        "geometry": mapping(LineString(path)),
        "properties": {
            "start_coord": start_coord,
            "end_coord": end_coord,
            "path_length": dist,
            "transit_go": travel_go,
            "transit_back": travel_return,
            "path_elevation": total_ascent
        }
    }
    
    # --- Étape 7 : Extraire les POI proches du tracé (<= 200m) ---
    try:
        near_pois = extract_pois_near_path(path, poi_data, max_distance_m=200)
    except Exception as e:
        print(f"⚠️ Erreur lors de l'extraction des POI proches: {e}")
        near_pois = []

    feature["properties"]["near_pois"] = near_pois
    print("✅ Itinéraire GeoJSON construit avec POI proches ajoutés.")
    
    return {
        "type": "FeatureCollection",
        "features": [feature]
    }


if __name__ == "__main__":
    # Exemple de paramètres
    randomness = 0.25
    city = "Lyon"
    departure_time = "2025-08-26T08:00:00"
    return_time = "2025-08-26T20:00:00"
    level = "intermediaire"
    
    if not settings.configured:
        settings.configure(
            USE_MOCK_DATA=False, 
            USE_MOCK_ROUTE_CREATION=True, 
            BASE_DIR=os.path.dirname(os.path.abspath(__file__))
        )
    
    try:
        result = compute_best_route(
            randomness=randomness,
            city=city,
            departure_time=departure_time,
            return_time=return_time,
            level=level,
        )

        print("=== Résultat ===")
        if "features" in result and len(result["features"]) > 0:
            props = result["features"][0]["properties"]
            print(f"Distance totale : {props.get('path_length', 'N/A')} m")
            print(f"Dénivelé positif : {props.get('path_elevation', 'N/A')} m")
            print(f"POI proches trouvés : {len(props.get('near_pois', []))}")

    except Exception as e:
        print("❌ Erreur pendant le test :", e)
