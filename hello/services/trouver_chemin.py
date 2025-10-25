import pickle
import json
import random
import requests
import time
from datetime import datetime, timedelta, time as dtime
import os
from dotenv import load_dotenv
from typing import Tuple, Dict, Any, List
from networkx import shortest_path, NetworkXNoPath
from shapely.geometry import LineString, mapping, Point
from zoneinfo import ZoneInfo
from django.conf import settings
import math
from hello.management.commands.utils import slugify

# ---- Chargement des données ----
load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_API_KEY")  

# ---- Calcul du point de départ ----

def get_best_transit_route(randomness=0.25, city="Lyon", departure_time=None, return_time=None,
                           stops_data=None, gares=None):
    """
    Sélectionne le meilleur arrêt selon le score et récupère un itinéraire de transport en commun via Google Maps.
    Ajoute des règles temporelles :
    - Départ matin/journée : max +6h
    - Départ soir (>18h) : max +18h
    - Vérifie que l'arrivée sur place laisse au moins 4h de marche avant le retour
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
        rand_factor = random.random()
        score_final = (1 - randomness) * score + randomness * rand_factor
        scored_stops.append((score_final, stop_id, stop_info))

    scored_stops.sort(reverse=True, key=lambda x: x[0])

    # --- Mode MOCK ---
    if getattr(settings, "USE_MOCK_ROUTE_CREATION", False):
        best_stop_info = scored_stops[0][2]
        dest_coords = best_stop_info["node"]  # (lon, lat)

        file_path = os.path.join(settings.BASE_DIR, "data/paths/optimized_routes_example.geojson")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "transit_go" in data["features"][0]["properties"]:
            leg = data["features"][0]["properties"]["transit_go"]["routes"][0]["legs"][0]
            transit_steps = [s for s in leg["steps"] if s["travelMode"] == "TRANSIT"]
            if transit_steps:
                last_step = transit_steps[-1]
                last_step["endLocation"]["latLng"] = {"latitude": dest_coords[0], "longitude": dest_coords[1]}
                last_step["transitDetails"]["stopDetails"]["arrivalTime"] = (departure_time + timedelta(minutes=120)).isoformat()
            leg["duration"] = "7200s"
        return data["features"][0]["properties"]["transit_go"]

    if city not in gares:
        raise ValueError(f"❌ Ville '{city}' non trouvée dans gares_departs.json")

    origin_coords = [gares[city]["latitude"], gares[city]["longitude"]]
    origin = {"latLng": {"latitude": origin_coords[0], "longitude": origin_coords[1]}}

    # --- Parcourir les meilleurs arrêts ---

    # si departure_time est naïf, on le rend aware
    if departure_time.tzinfo is None:
        departure_time = departure_time.replace(tzinfo=ZoneInfo("Europe/Paris"))

    # idem pour return_time
    if return_time.tzinfo is None:
        return_time = return_time.replace(tzinfo=ZoneInfo("Europe/Paris"))

    for score_final, stop_id, stop_info in scored_stops:
        dest_coords = stop_info["node"]
        destination = {"latLng": {"latitude": dest_coords[1], "longitude": dest_coords[0]}}
        body = {
            "origin": {"location": origin},
            "destination": {"location": destination},
            "travelMode": "TRANSIT",
            "departureTime": departure_time.replace(tzinfo=ZoneInfo("Europe/Paris")).isoformat(),
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

            leg = data.get("routes", [{}])[0].get("legs", [{}])[0]
            steps = leg.get("steps", [])
            transit_steps = [s for s in steps if s.get("travelMode") == "TRANSIT"]

            # --- Cas aucun step TRANSIT ---
            if not transit_steps:
                print(f"⚠️ Aucun step TRANSIT pour {stop_id}")
                stop_info["failure_count"] = stop_info.get("failure_count", 0) + 1
                print(f"⚠️ Compteur échec pour {stop_id} = {stop_info['failure_count']}")

                # Suppression si compteur >= 20
                if stop_info["failure_count"] >= 20:
                    print(f"❌ Suppression définitive de l'arrêt {stop_id}")
                    stops_data.pop(stop_id)

                time.sleep(1)
                continue

            stop_info["failure_count"] = 0  # reset compteur en cas de succès

            # --- Vérification de la fenêtre horaire ---
            dep_time_str = transit_steps[0]["transitDetails"]["stopDetails"]["departureTime"]
            dep_time = datetime.fromisoformat(dep_time_str).astimezone(ZoneInfo("Europe/Paris"))

            max_delay_h = 18 if departure_time.hour >= 18 else 6
            min_delay_h = -1

            if not (timedelta(hours=min_delay_h) <= dep_time - departure_time <= timedelta(hours=max_delay_h)):
                print(f"⏰ Départ trop éloigné ({dep_time - departure_time}), on ignore {stop_id}")
                continue

            # --- Vérification avec heure de retour ---
            arrival_time_str = transit_steps[-1]["transitDetails"]["stopDetails"]["arrivalTime"]
            arrival_time = datetime.fromisoformat(arrival_time_str).astimezone(ZoneInfo("Europe/Paris"))
            est_travel_duration = arrival_time - dep_time

            remaining_walk_time = (return_time - arrival_time) - est_travel_duration
            if remaining_walk_time.total_seconds() < 4 * 3600:
                print(f"🚫 Trajet vers {stop_id} trop tard pour le retour (temps de marche <4h)")
                continue

            print(f"✅ Itinéraire valide trouvé depuis l'arrêt {stop_id} (score={score_final:.3f})")
            return data

        except Exception as e:
            time.sleep(1)
            print(f"⚠️ Tentative échouée pour l'arrêt {stop_id} ({score_final:.3f}): {e}")
            continue

    raise RuntimeError("Aucun itinéraire de transport en commun trouvé respectant les contraintes temporelles")


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
        'debutant': 8_000,
        'intermediaire': 16_000,
        'avance': 25_000,
        'expert': 40_000
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
    duration_str = transit_route["routes"][0]["legs"][0]["duration"]
    transit_seconds_return = int(duration_str.replace("s", ""))
    end_walk = return_time - timedelta(seconds=transit_seconds_return)
    start_walk = datetime.combine(return_time.date(), dtime(8, 0), tzinfo=return_time.tzinfo)
    available_seconds = (end_walk - start_walk).total_seconds()
    fraction_last_day = max(0, available_seconds / max_walk_seconds_per_day)
    distance_last_day = max(min_distance_day1, dist_per_day * fraction_last_day)
    # Distance totale maximale
    if nb_days == 1:
        distance_max_m = distance_day1
    else:
        # jour 1 + jours intermédiaires + dernier jour - distance pour rejoindre l'arrêt aller et retour
        distance_max_m = distance_day1 + dist_per_day * (nb_days - 2) + distance_last_day - distance_to_transit_stop * 2 
    return distance_max_m

# ---- Calcul de l'itinéraire ----

def haversine(coord1, coord2):
    """Distance (m) entre deux points (lat, lon)."""
    R = 6371000
    lat1, lon1 = map(math.radians, coord1)
    lat2, lon2 = map(math.radians, coord2)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 2 * R * math.asin(math.sqrt(a))

def find_nearest_node(G, coord):
    """Trouve le nœud du graphe le plus proche d'une coordonnée (lat, lon)."""
    return min(G.nodes, key=lambda n: haversine(coord, (n[1], n[0])))

def angle_between(p1, p2, p3):
    """Cosinus de l’angle entre (p1→p2) et (p2→p3)."""
    v1 = (p2[0] - p1[0], p2[1] - p1[1])
    v2 = (p3[0] - p2[0], p3[1] - p2[1])
    dot = v1[0]*v2[0] + v1[1]*v2[1]
    norm1 = math.sqrt(v1[0]**2 + v1[1]**2)
    norm2 = math.sqrt(v2[0]**2 + v2[1]**2)
    if norm1 == 0 or norm2 == 0:
        return 0
    cos_theta = dot / (norm1 * norm2)
    return max(-1.0, min(1.0, cos_theta))

def path_has_crossing(path_nodes, new_segment_nodes):
    """
    Retourne True si le nouveau segment croise le chemin existant.
    """
    if len(path_nodes) < 2 or len(new_segment_nodes) < 2:
        return False

    current_line = LineString(path_nodes)
    new_line = LineString(new_segment_nodes)
    return current_line.crosses(new_line)

def best_hiking_path(start_coord, max_distance_m, G, poi_data, randomness=0.3, penalty_factor=100):
    """
    Algorithme frugal + aléatoire avec pénalisation des arêtes déjà parcourues.
    - randomise les scores par formule : (1 - r)*base + r*uniform(0,1)
    - sélectionne le meilleur POI et teste successivement suivant l'ordre décroissant
      si le meilleur n'est pas utilisable (pas de chemin, croisement, dépassement), on teste le suivant
    - si aucun POI accepté après 10 essais et croisement uniquement, on repêche le premier POI croisé
    - ajoute tous les POI à moins de 1000 m du segment au set des POI visités
    Retour : (best_path_nodes, best_dist_m)
    """
    # --- Préparer POI avec randomisation ---
    pois = []
    for feat in poi_data.get("features", []):
        base_score = float(feat["properties"].get("score", 0.0))
        noisy_score = (1 - randomness) * base_score + randomness * random.uniform(0, 1)
        pois.append({
            "id": feat["properties"].get("titre"),
            "coord": tuple(feat["geometry"]["coordinates"]),  # (lon, lat)
            "score": noisy_score
        })

    print(f"Chargés {len(pois)} POI (randomness={randomness:.2f})")

    # --- Initialisation ---
    current_node = find_nearest_node(G, start_coord[::-1])
    best_path = [current_node]
    best_dist = 0.0
    visited_pois = set()
    visited_edges = set()
    max_candidate_trials = 10

    # fonction de coût dynamique
    def edge_cost(u, v, d):
        cost = d["length"] / (d.get("score", 0.0) + 1e-6)
        if (u, v) in visited_edges or (v, u) in visited_edges:
            cost *= penalty_factor
        return cost

    step = 0
    while best_dist <= max_distance_m - 5000:
        step += 1
        print(f"\n=== Étape {step} — distance actuelle {best_dist/1000:.2f} km ===")

        # --- Filtrer candidats non visités dans rayon ---
        radius_m = 5000
        candidates = [p for p in pois if p["id"] not in visited_pois and
                      haversine(current_node[::-1], p["coord"][::-1]) <= radius_m]
        if not candidates:
            radius_m *= 2
            candidates = [p for p in pois if p["id"] not in visited_pois and
                          haversine(current_node[::-1], p["coord"][::-1]) <= radius_m]
        if not candidates:
            print("Aucun POI accessible — fin de boucle")
            break

        # --- Trier par score ---
        candidates_sorted = sorted(candidates, key=lambda p: p["score"], reverse=True)
        accepted = False
        trials = 0
        first_crossed_poi = None
        all_over_budget = True  # ← ajout : pour détecter le cas où tous les POI dépassent la distance max

        for poi in candidates_sorted:
            if trials >= max_candidate_trials:
                print(f"Limite de {max_candidate_trials} essais atteinte pour cette étape.")
                break
            trials += 1

            print(f"Essai #{trials} pour POI '{poi['id']}' (score bruité={poi['score']:.4f})")
            poi_node = find_nearest_node(G, poi["coord"][::-1])

            try:
                path_nodes = shortest_path(G, current_node, poi_node, weight=edge_cost)
            except NetworkXNoPath:
                print(f"  - Pas de chemin vers {poi['id']} (NetworkXNoPath). On essaie le suivant.")
                visited_pois.add(poi["id"])
                continue
            except Exception as e:
                print(f"  - Erreur lors du calcul du chemin vers {poi['id']}: {e}. On essaie le suivant.")
                continue

            # distance réelle du segment
            seg_len = 0.0
            bad_length = False
            for u, v in zip(path_nodes[:-1], path_nodes[1:]):
                if "length" not in G[u][v]:
                    print(f"  - Avertissement : l'arête ({u},{v}) n'a pas d'attribut 'length'. Rejet du POI.")
                    bad_length = True
                    break
                seg_len += G[u][v]["length"]
            if bad_length:
                continue

            if best_dist + seg_len > max_distance_m:
                print(f"  - Le segment vers {poi['id']} dépasse le budget restant. On essaie le suivant.")
                continue
            else:
                all_over_budget = False  # au moins un POI est dans le budget

            # vérifier croisement
            crosses = path_has_crossing(best_path, path_nodes)
            if crosses:
                print(f"  - Rejeté: le segment vers {poi['id']} croise le chemin existant.")
                if first_crossed_poi is None:
                    first_crossed_poi = (poi, path_nodes, seg_len)
                continue

            # OK : on accepte ce POI
            print(f"  + Accepté : POI {poi['id']} (seg_len={seg_len:.1f} m).")
            best_path.extend(path_nodes[1:])
            best_dist += seg_len
            current_node = path_nodes[-1]
            visited_pois.add(poi["id"])
            accepted = True

            # --- Ajouter tous les POI à moins de 1000 m du segment ---
            if len(path_nodes) >= 2:
                line_geom = LineString(path_nodes)
                for other_poi in pois:
                    if other_poi["id"] not in visited_pois:
                        pt = Point(other_poi["coord"])
                        if line_geom.distance(pt) <= 1000 / 111320:  # m -> degrés approx
                            visited_pois.add(other_poi["id"])
                            print(f"    - POI ajouté par proximité <1000m : {other_poi['id']}")

            # --- Marquer arêtes visitées ---
            for u, v in zip(path_nodes[:-1], path_nodes[1:]):
                visited_edges.add((u, v))

            break  # étape suivante

        # --- Si aucun POI accepté et qu'on a un POI croisé, on le repêche ---
        if not accepted and first_crossed_poi is not None:
            poi, path_nodes, seg_len = first_crossed_poi
            print(f"⚠ Aucun POI accepté après {max_candidate_trials} essais ; on reprend malgré croisement : {poi['id']}")
            best_path.extend(path_nodes[1:])
            best_dist += seg_len
            current_node = path_nodes[-1]
            visited_pois.add(poi["id"])
            accepted = True

            if len(path_nodes) >= 2:
                line_geom = LineString(path_nodes)
                for other_poi in pois:
                    if other_poi["id"] not in visited_pois:
                        pt = Point(other_poi["coord"])
                        if line_geom.distance(pt) <= 1000 / 111320:
                            visited_pois.add(other_poi["id"])
                            print(f"    - POI ajouté par proximité <1000m : {other_poi['id']}")

            for u, v in zip(path_nodes[:-1], path_nodes[1:]):
                visited_edges.add((u, v))

        # --- Nouvelle condition : si les 10 essais ont échoué parce que tous les POI dépassent le budget, on sort ---
        if not accepted and all_over_budget:
            print("🚫 Tous les POI dépassent la distance max — arrêt de la recherche.")
            break

    print("\n=== Recherche terminée ===")
    print(f"Distance finale: {best_dist/1000:.2f} km, points: {len(best_path)}, POI visités: {len(visited_pois)}")
    return best_path, best_dist

def save_geojson(data, output_path="data/paths/optimized_routes.geojson"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        print(f"✅ GeoJSON sauvegardé dans {output_path}")

def compute_return_transit(path, return_time, city, G, stops_data, gares):
    """
    Calcule le trajet retour en transport en commun depuis le dernier point du path jusqu'à la ville.
    Ajoute également la marche jusqu'au premier arrêt de TC dans le path.
    """
    print(f" >>> Début du calcul du trajet retour pour la ville : {city}")

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
    for i, (_, stop_id, stop_coord) in enumerate(stops_list, start=1):
        print(f" Test de l'arrêt {i} : {stop_id} (coord={stop_coord})")

        origin = {"location": {"latLng": {"latitude": stop_coord[1], "longitude": stop_coord[0]}}}
        city_coords = [gares[city]["latitude"], gares[city]["longitude"]]
        destination = {"location": {"latLng": {"latitude": city_coords[0], "longitude": city_coords[1]}}}

        if getattr(settings, "USE_MOCK_ROUTE_CREATION", False):
            # --- MODE MOCK ---
            print(" Mode MOCK activé : lecture d’un itinéraire simulé.")
            file_path = os.path.join(settings.BASE_DIR, "data/paths/optimized_routes_example.geojson")
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            travel_back = data["features"][0]["properties"].get("transit_back")
            if travel_back:
                print(" Itinéraire simulé trouvé.")
                leg = travel_back["routes"][0]["legs"][0]
                transit_steps = [s for s in leg["steps"] if s["travelMode"] == "TRANSIT"]
                if transit_steps:
                    print(f" {len(transit_steps)} étapes de transit simulées.")
                    first_step = transit_steps[0]
                    last_step = transit_steps[-1]
                    first_step["startLocation"]["latLng"] = {"latitude": last_point[1], "longitude": last_point[0]}
                    last_step["endLocation"]["latLng"] = {"latitude": city_coords[0], "longitude": city_coords[1]}
                    last_step["transitDetails"]["stopDetails"]["arrivalTime"] = return_time.isoformat()
                leg["duration"] = "7200s"
            resp = travel_back

        else:
            # --- APPEL RÉEL À L’API GOOGLE ---
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
                "arrivalTime": return_time.replace(tzinfo=ZoneInfo("Europe/Paris")).isoformat(),
                "transitPreferences": {"routingPreference": "FEWER_TRANSFERS"},
            }

            r = requests.post(url, headers=headers, json=body)

            if r.status_code != 200:
                print(f" ❌ Erreur API pour l'arrêt {stop_id} : {r.text[:200]}")
                print(" ⏳ Pause d'une seconde avant de réessayer...")
                time.sleep(1)  
                continue

            resp = r.json()

        # --- TRAITEMENT DU RÉSULTAT ---
        steps = resp.get("routes", [{}])[0].get("legs", [{}])[0].get("steps", [])
        transit_steps = [s for s in steps if s.get("travelMode") == "TRANSIT"]

        if transit_steps:
            print(f" ✅ Itinéraire retour trouvé depuis l’arrêt {stop_id}.")
            # Reset compteur si succès
            stops_data[stop_id]["failure_count"] = 0
            return_transit_route = resp
            first_step_start = transit_steps[0]["startLocation"]["latLng"]
            break
        else:
            print(f" ⚠ Aucun transit trouvé depuis l’arrêt {stop_id}.")
            # Incrément compteur
            stop_info = stops_data.get(stop_id, {})
            stop_info["failure_count"] = stop_info.get("failure_count", 0) + 1
            print(f" ⚠ Compteur échec pour {stop_id} = {stop_info['failure_count']}")
            # Suppression si compteur >= 20
            if stop_info["failure_count"] >= 20:
                print(f" ❌ Suppression définitive de l'arrêt {stop_id}")
                stops_data.pop(stop_id)
            time.sleep(1)

    if return_transit_route is None:
        print(" ❌ Aucun itinéraire retour trouvé après 10 arrêts testés.")
        raise RuntimeError("Impossible de trouver un itinéraire retour en transport en commun.")

    # --- Ajouter la marche jusqu'au premier step TC ---
    print(" Calcul du chemin de marche vers le premier arrêt TC…")
    start_coord = (last_point[1], last_point[0])  # (lat, lon)
    end_coord = (first_step_start["latitude"], first_step_start["longitude"])

    start_node = find_nearest_node(G, start_coord)
    end_node = find_nearest_node(G, end_coord)
    if start_node is None or end_node is None:
        print(" ❌ Impossible de trouver les noeuds du graphe pour la marche finale.")
        raise RuntimeError("Impossible de trouver les noeuds du graphe pour la marche finale.")

    sp_nodes = shortest_path(G, source=start_node, target=end_node, weight="length")

    augmented_path = path + sp_nodes[1:]
    best_dist = sum(G[u][v]["length"] for u, v in zip(augmented_path[:-1], augmented_path[1:]))
    print(f" Distance totale estimée : {best_dist:.1f} m")

    print(" ✅ Calcul du trajet retour terminé avec succès.")
    return augmented_path, return_transit_route, best_dist

def get_elevations(path):
    """
    Récupère les altitudes depuis l'API Open-Elevation.
    path : liste de tuples (lon, lat)
    """
    locations = [{"latitude": lat, "longitude": lon} for lon, lat in path]
    url = "https://api.open-elevation.com/api/v1/lookup"
    response = requests.post(url, json={"locations": locations})
    response.raise_for_status()
    results = response.json()["results"]
    elevations = [pt["elevation"] for pt in results]
    return elevations

def smooth_elevations(elevations, window=3):
    """
    Lisse les altitudes avec une moyenne mobile.
    window : taille de la fenêtre de lissage (impair recommandé)
    """
    smoothed = []
    n = len(elevations)
    half_window = window // 2
    for i in range(n):
        start = max(0, i - half_window)
        end = min(n, i + half_window + 1)
        smoothed.append(sum(elevations[start:end]) / (end - start))
    return smoothed

def compute_total_ascent(elevations, min_diff=2):
    """
    Calcule le dénivelé positif total.
    min_diff : variation minimale à prendre en compte pour éviter le bruit
    """
    total_ascent = 0
    for i in range(1, len(elevations)):
        delta = elevations[i] - elevations[i-1]
        if delta > min_diff:
            total_ascent += delta
    return round(total_ascent)

# ---- Fonction principale combinée ----
def compute_best_route(randomness=0.2, city="Lyon", massif="Chartreuse",
                       departure_time: datetime = None, return_time: datetime = None,
                       level: str = "intermediaire"):    
    """
    Planifie une randonnée en utilisant le meilleur itinéraire en transport .replace(tzinfo=None)en commun pour atteindre le départ.
    """

    massif_clean = slugify(massif)

    stops_path = f"data/output/{massif_clean}_stop_node_mapping.json"
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
        file_path = os.path.join(settings.BASE_DIR, "data/paths/optimized_routes_example.geojson")
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
        
    
    departure_time = datetime.fromisoformat(departure_time)
    return_time = datetime.fromisoformat(return_time)
    for stop_id, stop_info in stops_data.items():
        stop_info.setdefault("failure_count", 0) #compteur d'échecs pour possible suppression d'un arrêt inatteignable

    # --- Étape 1 : Récupérer l'itinéraire de transport en commun ---
    travel_go = get_best_transit_route(randomness=randomness, city=city, departure_time=departure_time, return_time=return_time, stops_data=stops_data, gares=gares)
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
    print(f"Distance maximale de randonnée estimée : {max_distance_m/1000:.1f} km")
    # --- Étape 4 : Lancer la recherche du meilleur chemin de randonnée ---
    path, dist = best_hiking_path(start_coord=(transit_end[0], transit_end[1]), max_distance_m=max_distance_m, G=G, poi_data=poi_data,randomness=randomness)
    print(f"Distance de randonnée planifiée : {dist/1000:.1f} km")
    # --- Étape 5 : Calculer l'itinéraire retour en transport en commun ---
    path, travel_return, dist = compute_return_transit(path, return_time, city, G=G, stops_data=stops_data, gares=gares)
    print(f"Distance totale avec retour en TC : {dist/1000:.1f} km")
    
    # --- Etape 5b : Récupérer les élévations ---
    elevations = get_elevations(path)
    smoothed_elevations = smooth_elevations(elevations, window=10)  # window à ajuster selon la densité des points
    total_ascent = compute_total_ascent(smoothed_elevations)

    # Ajouter les élévations au GeoJSON
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
    print("✅ Itinéraire GeoJSON construit.")
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
    k = 50
    graph_path = "data/output/hiking_graph.gpickle"
    if not settings.configured:
        settings.configure(USE_MOCK_DATA=False, USE_MOCK_ROUTE_CREATION=True, BASE_DIR=os.path.dirname(os.path.abspath(__file__)))
    try:
        result = compute_best_route(
            randomness=randomness,
            city=city,
            departure_time=departure_time,
            return_time=return_time,
            level=level,
        )

        print("=== Résultat ===")
        print(f"Distance randonnée : {result['hiking_distance']} m")
        print(f"Score randonnée : {result['hiking_score']}")
        print(f"Nombre d'étapes (noeuds) : {len(result['hiking_path'])}")
        print("Coordonnées départ randonnée :", result['hiking_path'][0] if result['hiking_path'] else "N/A")

    except Exception as e:
        print("❌ Erreur pendant le test :", e)
