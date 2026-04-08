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
from networkx import NetworkXNoPath, shortest_path

from .geotools import save_geojson_gpx, haversine, find_nearest_node
from .transit import (
    get_best_transit_route,
    choose_return_stop,
    compute_return_transit,
)
from .route_init import initialize_route_parameters
from .hiking import best_hiking_crossing, best_hiking_massif_tour, best_hiking_loop, extract_pois_near_path, _get_massif_center
from .elevation import get_elevations, smooth_elevations, compute_total_ascent


def compute_best_route(
    randomness=0.2,
    massif="Chartreuse",
    departure_time: datetime = None,
    return_time: datetime = None,
    level: str = "intermediaire",
    address: str = "",
    transit_priority: str = "balanced",
):
    """
    Planifie une randonnée complète :
    1. Choix arrêt aller
    2. Distance max
    3. Route type
    4. Choix arrêt retour
    5. Génération chemin rando
    6. Retour TC
    """

    massif_clean = slugify(massif)

    stops_path = f"data/output/{massif_clean}_arrets_stop_node_mapping.json"
    graph_path = f"data/output/{massif_clean}_hiking_graph.gpickle"
    poi_file = f"data/output/{massif_clean}_poi_scores.geojson"
    hubs_entree_path = f"data/output/{massif_clean}_hubs_entree.geojson"

    for path in [stops_path, graph_path, poi_file, hubs_entree_path]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"❌ Fichier introuvable : {path}")

    with open(stops_path, "r", encoding="utf-8") as f:
        stops_data = json.load(f)

    with open(graph_path, "rb") as f:
        G = pickle.load(f)

    with open(poi_file, "r", encoding="utf-8") as f:
        poi_data = json.load(f)

    with open(hubs_entree_path, "r", encoding="utf-8") as f:
        hubs_entree_data = json.load(f)

    if getattr(settings, "USE_MOCK_DATA", False):
        file_path = os.path.join(
            settings.BASE_DIR,
            "hello/static/hello/data/optimized_routes_example.geojson"
        )
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    departure_time = datetime.fromisoformat(departure_time)
    return_time = datetime.fromisoformat(return_time)

    # --- 1. Transport aller ---
    travel_go = get_best_transit_route(
        randomness=randomness,
        departure_time=departure_time,
        return_time=return_time,
        stops_data=stops_data,
        address=address,
        transit_priority=transit_priority,
        hubs_entree_data=hubs_entree_data,
    )

    transit_end = None
    departure_stop_id = None

    if travel_go:
        steps = travel_go[0]["routes"][0]["legs"][0]["steps"]
        transit_steps = [s for s in steps if s["travelMode"] == "TRANSIT"]

        if transit_steps:
            last_transit = transit_steps[-1]
            end_lat = last_transit["endLocation"]["latLng"]["latitude"]
            end_lon = last_transit["endLocation"]["latLng"]["longitude"]
            transit_end = (end_lon, end_lat)

    if transit_end is None:
        raise RuntimeError("Impossible de déterminer le point départ randonnée.")

    # retrouver stop départ le plus proche
    departure_stop_id = min(
        stops_data.keys(),
        key=lambda sid: (
            (stops_data[sid]["node"][0] - transit_end[0]) ** 2
            + (stops_data[sid]["node"][1] - transit_end[1]) ** 2
        )
    )

    departure_stop_info = stops_data[departure_stop_id]

    # --- 2. Distance max + route_type ---
    max_distance_m, route_type = initialize_route_parameters(
        massif_name=massif,
        departure_time=departure_time,
        return_time=return_time,
        level=level,
        transit_route=travel_go
    )

    print(f"Distance max : {max_distance_m/1000:.1f} km")
    print(f"Route type : {route_type}")

    selected_candidate = None
    selected_return_duration = None
    selected_hike_path = None
    selected_hike_distance = None
    selected_travel_return = None
    return_error_message = None

    if route_type == "crossing":
        # Logique crossing : choisir d'abord l'arrêt retour, puis faire la randonnée
        try:
            return_candidates = choose_return_stop(
                departure_stop_info=departure_stop_info,
                stops_data=stops_data,
                distance_max_m=max_distance_m,
                transit_priority=transit_priority,
            )
        except Exception as e:
            return_candidates = []
            return_error_message = f"Aucun arrêt retour plausible trouvé : {e}"
            print(f"⚠️ {return_error_message}")

        # Boucle de tentative sur le classement de retours
        print(f"{len(return_candidates)} candidats retour trouvés, tentative de calcul des itinéraires...")
        for candidate in return_candidates:
            try:
                selected_candidate, selected_travel_return, selected_return_duration = compute_return_transit(
                    [candidate], return_time, address, stops_data=stops_data, departure_time=departure_time
                )
            except Exception as e:
                print(f"⚠️ Pas de retour TC pour candidat {candidate.get('stop_id')}: {e}")
                continue

            # Recalculer la distance max connaissant la durée de retour TC
            max_distance_m, route_type = initialize_route_parameters(
                massif_name=massif,
                departure_time=departure_time,
                return_time=return_time,
                level=level,
                transit_route=travel_go,
                return_transit_seconds=selected_return_duration,
            )

            print(f"Distance max ajustée avec retour connu : {max_distance_m/1000:.1f} km")

            # Vérifier si c'est une boucle (arrêt retour = arrêt aller)
            is_loop = candidate.get("stop_id") == departure_stop_id
            
            if is_loop:
                print(f"🔁 Cas boucle détecté : arrêt retour = arrêt aller, utilisation du mode boucle")
                try:
                    path, dist = best_hiking_loop(
                        start_coord=departure_stop_info["node"],
                        max_distance_m=max_distance_m,
                        G=G,
                        poi_data=poi_data,
                        randomness=randomness,
                        massif_name=massif_clean,
                    )
                except Exception as e:
                    print(f"⚠️ Échec chemin boucle pour candidat {candidate.get('stop_id')}: {e}")
                    continue
            else:
                try:
                    path, dist = best_hiking_crossing(
                        start_coord=departure_stop_info["node"],
                        end_coord=candidate["stop_info"]["node"],
                        max_distance_m=max_distance_m,
                        G=G,
                        poi_data=poi_data,
                        randomness=randomness,
                    )
                except Exception as e:
                    print(f"⚠️ Échec chemin randonnée pour candidat {candidate.get('stop_id')}: {e}")
                    continue

            selected_candidate = candidate
            selected_hike_path = path
            selected_hike_distance = dist

            break

        if selected_candidate is None:
            return_error_message = return_error_message or "Aucun itinéraire retour TC valide trouvé pour crossing"
            print(f"⚠️ {return_error_message}")

            if return_candidates:
                fallback_candidate = return_candidates[0]
                try:
                    selected_hike_path, selected_hike_distance = best_hiking_crossing(
                        start_coord=departure_stop_info["node"],
                        end_coord=fallback_candidate["stop_info"]["node"],
                        max_distance_m=max_distance_m,
                        G=G,
                        poi_data=poi_data,
                        randomness=randomness,
                    )
                    print(f"⚠️ Trajet randonnée de repli calculé vers {fallback_candidate.get('stop_id')} malgré absence de retour TC")
                except Exception as e:
                    print(f"⚠️ Échec du trajet de repli pour {fallback_candidate.get('stop_id')}: {e}")
                    selected_hike_path = []
                    selected_hike_distance = 0
            else:
                selected_hike_path = []
                selected_hike_distance = 0

    elif route_type == "massif_tour":
        # Logique massif_tour : faire d'abord la randonnée, puis trouver l'arrêt retour
        print("🔄 Mode massif_tour : calcul de la randonnée d'abord...")
        
        try:
            hike_path, hike_distance = best_hiking_massif_tour(
                start_coord=departure_stop_info["node"],
                max_distance_m=max_distance_m,
                G=G,
                poi_data=poi_data,
                stops_data=stops_data,
                randomness=randomness,
                massif_name=massif_clean,
            )
            print(f"Distance randonnée tour : {hike_distance/1000:.1f} km")
        except Exception as e:
            raise RuntimeError(f"Échec calcul randonnée massif_tour : {e}")

        # Déterminer le point d'arrivée de la randonnée
        if not hike_path:
            raise RuntimeError("Aucun chemin de randonnée trouvé pour massif_tour")

        final_coord = hike_path[-1]  #

        # Calculer la distance restante
        remaining_distance = max_distance_m - hike_distance
        print(f"Distance restante après randonnée : {remaining_distance/1000:.1f} km")

        # Créer un faux departure_stop_info pour le point d'arrivée
        # pour pouvoir utiliser choose_return_stop
        arrival_stop_info = {
            "node": final_coord,
            "properties": {}  # Propriétés vides, choose_return_stop gère les valeurs par défaut
        }

        # Utiliser choose_return_stop depuis le point d'arrivée avec distance_max=20km
        try:
            return_candidates = choose_return_stop(
                departure_stop_info=arrival_stop_info,
                stops_data=stops_data,
                distance_max_m=20000,  # 20km
                transit_priority=transit_priority,
            )
        except Exception as e:
            return_candidates = []
            print(f"⚠️ Erreur recherche retour 20km: {e}")

        # Si aucun candidat dans 20km, élargir à 50km
        if not return_candidates:
            print(f"⚠️ Aucun arrêt retour trouvé dans 20km, élargissement à 50km...")
            try:
                return_candidates = choose_return_stop(
                    departure_stop_info=arrival_stop_info,
                    stops_data=stops_data,
                    distance_max_m=50000,  # 50km
                    transit_priority=transit_priority,
                )
            except Exception as e:
                return_candidates = []
                return_error_message = f"Aucun arrêt retour plausible trouvé même dans un rayon de 50km"
                print(f"⚠️ {return_error_message}")

        selected_candidate = None
        selected_return_duration = None
        selected_travel_return = None

        # Boucle sur les candidats retour depuis le point d'arrivée
        print(f"{len(return_candidates)} candidats retour depuis l'arrivée trouvés")
        for candidate in return_candidates:
            try:
                selected_candidate, selected_travel_return, selected_return_duration = compute_return_transit(
                    [candidate], return_time, address, stops_data=stops_data, departure_time=departure_time
                )
                break  # Prendre le premier qui marche
            except Exception as e:
                print(f"⚠️ Pas de retour TC depuis {candidate.get('stop_id')}: {e}")
                continue

        # Si aucun candidat n'a de TC valide dans 20km, élargir à 50km
        if selected_candidate is None and return_candidates:
            print(f"⚠️ Aucun arrêt retour avec TC valide trouvé dans 20km, élargissement à 50km...")
            try:
                return_candidates_50km = choose_return_stop(
                    departure_stop_info=arrival_stop_info,
                    stops_data=stops_data,
                    distance_max_m=50000,  # 50km
                    transit_priority=transit_priority,
                )
            except Exception as e:
                return_candidates_50km = []
                print(f"⚠️ Erreur recherche retour 50km: {e}")
            
            # Tenter les candidats 50km
            for candidate in return_candidates_50km:
                try:
                    selected_candidate, selected_travel_return, selected_return_duration = compute_return_transit(
                        [candidate], return_time, address, stops_data=stops_data, departure_time=departure_time
                    )
                    break  # Prendre le premier qui marche
                except Exception as e:
                    print(f"⚠️ Pas de retour TC depuis {candidate.get('stop_id')} (50km): {e}")
                    continue

        if selected_candidate is None:
            return_error_message = return_error_message or "Aucun arrêt retour valide trouvé même après élargissement à 50km"
            print(f"⚠️ {return_error_message}")
            selected_hike_path = hike_path
            selected_hike_distance = hike_distance
        else:
            # Ajouter le trajet piéton du point d'arrivée vers l'arrêt TC choisi
            print(f"🛤️ Ajout trajet piéton vers arrêt TC {selected_candidate.get('stop_id')}")
            
            try:
                # Trouver les nœuds les plus proches (coordonnées sont lon/lat, graphe utilise lat/lon)
                start_node = find_nearest_node(G, final_coord[::-1])  # (lat, lon)
                end_node = find_nearest_node(G, selected_candidate["stop_info"]["node"][::-1])  # (lat, lon)
                
                # Calculer le chemin le plus court
                path_to_stop = shortest_path(G, start_node, end_node, weight='length')
                
                # Calculer la distance
                distance_to_stop = sum(
                    G[path_to_stop[i]][path_to_stop[i+1]]['length'] 
                    for i in range(len(path_to_stop)-1)
                )
                
                print(f"Distance vers arrêt TC : {distance_to_stop/1000:.1f} km")
                
                # Ajouter le chemin (sauf le premier point qui est déjà dans hike_path)
                hike_path.extend(path_to_stop[1:])
                hike_distance += distance_to_stop
                
            except NetworkXNoPath:
                return_error_message = f"Aucun chemin piéton vers l'arrêt TC {selected_candidate.get('stop_id')}"
                print(f"⚠️ {return_error_message}")
            except Exception as e:
                return_error_message = f"Erreur calcul trajet vers arrêt TC : {e}"
                print(f"⚠️ {return_error_message}")

            selected_hike_path = hike_path
            selected_hike_distance = hike_distance

    else:
        raise ValueError(f"route_type inconnu : {route_type}")

    # --- 4. Variables communes ---
    if selected_hike_path is None:
        selected_hike_path = []
        selected_hike_distance = 0

    path = selected_hike_path
    dist = selected_hike_distance
    travel_return = selected_travel_return

    print(f"Distance randonnée finale : {dist/1000:.1f} km")

    path = selected_hike_path
    dist = selected_hike_distance
    travel_return = selected_travel_return

    print(f"Distance randonnée finale : {dist/1000:.1f} km")

    # --- 6. Altitudes ---
    if not path:
        elevations = []
        elevation_failed = True
        smoothed_elevations = []
        total_ascent = 0
    else:
        elevations = get_elevations(path)
        elevation_failed = all(ele == 0 for ele in elevations)

        smoothed_elevations = smooth_elevations(elevations, window=10)
        total_ascent = compute_total_ascent(smoothed_elevations)

    path = [
        [lon, lat, round(ele)]
        for (lon, lat), ele in zip(path, smoothed_elevations)
    ]

    extra_props = {}
    if elevation_failed:
        extra_props["elevation_error"] = True
    if return_error_message:
        extra_props["return_error"] = True
        extra_props["return_error_message"] = return_error_message

    # --- 7. GeoJSON ---
    props = {
        "start_coord": path[0],
        "end_coord": path[-1],
        "path_length": dist,
        "route_type": route_type,
        "transit_go": travel_go[0],
        "transit_back": travel_return,
        "path_elevation": total_ascent,
    }

    props.update(extra_props)

    feature = {
        "type": "Feature",
        "geometry": mapping(LineString(path)),
        "properties": props,
    }

    # --- 8. POI proches ---
    try:
        near_pois = extract_pois_near_path(path, poi_data, max_distance_m=200)
    except Exception as e:
        print(f"⚠️ erreur POI : {e}")
        near_pois = []

    feature["properties"]["near_pois"] = near_pois

    result = {
        "type": "FeatureCollection",
        "features": [feature]
    }

    # --- 9. Sauvegarde ---
    try:
        params_part = f"{address}_{massif_clean}_{slugify(level)}_r{int(randomness*100)}"
    except Exception:
        params_part = f"{address}_{massif_clean}"

    ts_ms = int(datetime.utcnow().timestamp() * 1000)
    filename_base = f"route_{params_part}_{ts_ms}"

    output_dir = os.path.join(
        settings.BASE_DIR,
        "hello",
        "static",
        "hello",
        "data"
    )
    os.makedirs(output_dir, exist_ok=True)

    output_geojson_path = os.path.join(
        output_dir,
        f"{filename_base}.geojson"
    )

    try:
        save_geojson_gpx(result, output_path=output_geojson_path)
        result["generated_filename"] = f"{filename_base}.geojson"
    except Exception as e:
        print(f"⚠️ erreur sauvegarde : {e}")

    # --- 10. Sauvegarde compteurs d'échec ---
    try:
        with open(stops_path, "w", encoding="utf-8") as f:
            json.dump(stops_data, f, indent=2, ensure_ascii=False)
        print(f"✅ Compteurs d'échec sauvegardés dans {stops_path}")
    except Exception as e:
        print(f"⚠️ Erreur sauvegarde compteurs d'échec : {e}")

    return result