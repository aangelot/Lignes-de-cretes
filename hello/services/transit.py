"""
Gestion des itinéraires de transport en commun (aller/retour).
Calcul de la distance maximale de randonnée en fonction du temps disponible.
"""

import json
import os
import random
import time
import requests
import re
import unicodedata
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from django.conf import settings
from networkx import shortest_path
from .geotools import geocode_address, haversine, find_nearest_node

# Charger la clé API Google
from dotenv import load_dotenv
load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_API_KEY")


def _normalize_label(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def _coords_from_station_label(label):
    """
    Cherche dans data/input/liste-des-gares.geojson une gare correspondant au libellé `label`.
    Retourne (lat, lon) si trouvée, sinon None.
    """
    try:
        gj_path = os.path.join(settings.BASE_DIR, "data", "input", "liste-des-gares.geojson")
        with open(gj_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        print(f"⚠️ Impossible de lire liste-des-gares.geojson : {e}")
        return None

    target = _normalize_label(label)
    if not target:
        return None

    for feat in data.get("features", []):
        props = feat.get("properties", {}) or {}
        lib = props.get("libelle") or props.get("name") or ""
        if _normalize_label(lib) == target:
            coords = feat.get("geometry", {}).get("coordinates")
            if coords and len(coords) >= 2:
                # GeoJSON coords: [lon, lat] -> return (lat, lon)
                return (coords[1], coords[0])
    return None


def get_best_transit_route(randomness=0.25, departure_time=None, return_time=None,
                           stops_data=None, address='', transit_priority="balanced", hubs_entree_data=None):
    """
    Sélectionne le meilleur arrêt selon le score et récupère un itinéraire de transport en commun via Google Maps.
    Ajoute des règles temporelles :
    - Départ matin/journée : max +6h
    - Départ soir (>18h) : max +18h
    - Vérifie que l'arrivée sur place laisse au moins 4h de marche avant le retour
    """
    # Tenter de récupérer les coordonnées à partir du libellé de gare (fallback geocoding)
    address_coords = _coords_from_station_label(address) or geocode_address(address)
    print(f"Coordonnées géocodées / station de l'adresse '{address}': {address_coords}")

    # Choisir le hub de départ le plus proche
    hubs_departs = []
    try:
        hubs_departs_path = os.path.join(settings.BASE_DIR, "data", "input", "hubs_departs.geojson")
        with open(hubs_departs_path, "r", encoding="utf-8") as hf:
            hubs_departs = json.load(hf).get("features", [])
    except Exception:
        hubs_departs = []
    # Charger les hubs d'entrée du massif sélectionné et les ajouter aux hubs de départ
    hubs_entree_features = hubs_entree_data.get("features", [])
    hubs_departs.extend(hubs_entree_features)

    departure_hub_name = None
    best = None
    for hf in hubs_departs:
        hub_coords = hf.get("geometry", {}).get("coordinates")
        d = haversine((address_coords[0], address_coords[1]), (hub_coords[1], hub_coords[0]))
        if best is None or d < best[0]:
            best = (d, hf)
    departure_hub_name = best[1].get("properties", {}).get("nom") or best[1].get("properties", {}).get("id")
    print(f"Hub de départ sélectionné : {departure_hub_name}")

    # Calculer durations (hub_depart -> hub_entree) + (hub_entree -> stop)
    duration_values = []
    for stop_id, stop_info in (stops_data or {}).items():
        props = stop_info.setdefault("properties", {})
        hub_entree_id = props.get("hub_entree")
        dur_hub_to_hub_entree = 10000.0
        matched = None
        for hf in hubs_entree_features:
            hid = hf.get("properties", {}).get("id") or hf.get("properties", {}).get("nom")
            if hid == hub_entree_id:
                matched = hf
                break
        if matched:
            dur_map = matched.get("properties", {}).get("durations_from_hubs", {})
            if departure_hub_name and isinstance(dur_map, dict):
                dur_hub_to_hub_entree = float(dur_map.get(departure_hub_name, 10000))
        if "duration" in props and props.get("duration") is not None:
            dur_hub_entree_to_stop = float(props.get("duration"))
        elif "duration_min_go" in props and props.get("duration_min_go") is not None:
            dur_hub_entree_to_stop = float(props.get("duration_min_go"))
        else:
            dur_hub_entree_to_stop = 10000.0

        total_min = dur_hub_to_hub_entree + dur_hub_entree_to_stop
        props["duration_min_go"] = total_min
        duration_values.append(total_min)

    minv = min(duration_values)
    maxv = max(duration_values)
    for stop_id, stop_info in (stops_data or {}).items():
        props = stop_info.setdefault("properties", {})
        val = props.get("duration_min_go")
        if val is None:
            props["duration_min_go_normalized"] = 1.0
        else:
            props["duration_min_go_normalized"] = (val - minv) / (maxv - minv)


    TRANSIT_WEIGHTS = {
        "balanced": {"duration": 0.4, "elevation": 0.3, "nature": 0.3},
        "fast": {"duration": 0.9, "elevation": 0.05, "nature": 0.05},
        "deep_nature": {"duration": 0.2, "elevation": 0.3, "nature": 0.5}
    }
    weights = TRANSIT_WEIGHTS.get(transit_priority, TRANSIT_WEIGHTS["balanced"])

    scored_stops = []
    for stop_id, stop_info in stops_data.items():
        props = stop_info.get("properties", {})
        score = (
            weights["duration"] * (1 - props.get("duration_min_go_normalized", 0))
            + weights["elevation"] * props.get("elevation_normalized", 0)
            + weights["nature"] * props.get("distance_to_pnr_border_normalized", 0)
        )
        rand_factor = random.random()
        score_final = (1 - randomness) * score + randomness * rand_factor
        scored_stops.append((score_final, stop_id, stop_info))

    scored_stops = [x for x in scored_stops if isinstance(x, tuple) and len(x) > 0 and isinstance(x[0], (int, float))]
    scored_stops.sort(reverse=True, key=lambda x: x[0])
    
    scored_stops = [x for x in scored_stops if isinstance(x, tuple) and len(x) > 0 and isinstance(x[0], (int, float))]
    scored_stops.sort(reverse=True, key=lambda x: x[0])

    # --- Mode MOCK ---
    if getattr(settings, "USE_MOCK_ROUTE_CREATION", False):
        best_stop_info = scored_stops[0][2]
        dest_coords = best_stop_info["node"]  # (lon, lat)

        file_path = os.path.join(settings.BASE_DIR, "hello/static/hello/data/optimized_routes_example.geojson")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "transit_go" in data["features"][0]["properties"]:
            leg = data["features"][0]["properties"]["transit_go"]["routes"][0]["legs"][0]
            transit_steps = [s for s in leg["steps"] if s["travelMode"] == "TRANSIT"]
            if transit_steps:
                last_step = transit_steps[-1]
                last_step["endLocation"]["latLng"] = {"latitude": dest_coords[1], "longitude": dest_coords[0]}
                last_step["transitDetails"]["stopDetails"]["arrivalTime"] = (departure_time + timedelta(minutes=120)).isoformat()
            leg["duration"] = "7200s"
        return data["features"][0]["properties"]["transit_go"]

    origin = {"latLng": {"latitude": address_coords[0], "longitude": address_coords[1]}}

    # --- Parcourir les meilleurs arrêts ---

    if departure_time.tzinfo is None:
        departure_time = departure_time.replace(tzinfo=ZoneInfo("Europe/Paris"))

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

            if not transit_steps:
                print(f"⚠️ Aucun step TRANSIT pour {stop_id}")
                stop_info["failure_count"] = stop_info.get("failure_count", 0) + 1
                print(f"⚠️ Compteur échec pour {stop_id} = {stop_info['failure_count']}")

                if stop_info["failure_count"] >= 20:
                    print(f"❌ Suppression définitive de l'arrêt {stop_id}")
                    stops_data.pop(stop_id)

                time.sleep(0.05)
                continue

            stop_info["failure_count"] = 0

            dep_time_str = transit_steps[0]["transitDetails"]["stopDetails"]["departureTime"]
            dep_time = datetime.fromisoformat(dep_time_str).astimezone(ZoneInfo("Europe/Paris"))

            max_delay_h = 18 if departure_time.hour >= 18 else 6
            min_delay_h = -1

            if not (timedelta(hours=min_delay_h) <= dep_time - departure_time <= timedelta(hours=max_delay_h)):
                print(f"⏰ Départ trop éloigné ({dep_time - departure_time}), on ignore {stop_id}")
                continue

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
            time.sleep(0.05)
            print(f"⚠️ Tentative échouée pour l'arrêt {stop_id} ({score_final:.3f}): {e}")
            continue

    raise RuntimeError("Aucun itinéraire de transport en commun trouvé respectant les contraintes temporelles")

def compute_max_hiking_distance(departure_time: datetime,
                                return_time: datetime,
                                level: str,
                                transit_route) -> float:
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


def _is_itinerary_on_target_day(transit_route, target_date):
    """
    Vérifie que l'itinéraire retourné par Google Maps est bien le jour souhaité.
    
    Args:
        transit_route: dictionnaire de réponse de Google Routes API
        target_date: date souhaitée (datetime.date)
    
    Returns:
        True si l'itinéraire est le bon jour, False sinon
    """
    try:
        steps = transit_route.get("routes", [{}])[0].get("legs", [{}])[0].get("steps", [])
        transit_steps = [s for s in steps if s.get("travelMode") == "TRANSIT"]
        
        if not transit_steps:
            return False
        
        # Vérifier le jour du dernier step TRANSIT (arrivée)
        arrival_str = transit_steps[-1].get("transitDetails", {}).get("stopDetails", {}).get("arrivalTime")
        if not arrival_str:
            return False
        
        arrival_time = datetime.fromisoformat(arrival_str.replace("Z", "+00:00"))
        arrival_date = arrival_time.date()
        
        return arrival_date == target_date
    except Exception as e:
        print(f"  ⚠️ Erreur lors de la vérification du jour : {e}")
        return False


def compute_return_transit(path, return_time, G, stops_data, address):
    """
    Calcule le trajet retour en transport en commun depuis le dernier point du path jusqu'à la ville.
    Ajoute également la marche jusqu'au premier arrêt de TC dans le path.
    
    Vérifie que l'itinéraire retourné est bien le jour souhaité. Si Google Maps retourne
    un itinéraire d'un autre jour (veille, avant-veille, etc.), l'arrêt est rejeté et
    on teste l'arrêt suivant.
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
    for i, (_, stop_id, stop_coord) in enumerate(stops_list, start=1):
        print(f" Test de l'arrêt {i} : {stop_id} (coord={stop_coord})")

        origin = {"location": {"latLng": {"latitude": stop_coord[1], "longitude": stop_coord[0]}}}
        address_coords = geocode_address(address)
        destination = {"location": {"latLng": {"latitude": address_coords[0], "longitude": address_coords[1]}}}

        if getattr(settings, "USE_MOCK_ROUTE_CREATION", False):
            # --- MODE MOCK ---
            print(" Mode MOCK activé : lecture d'un itinéraire simulé.")
            file_path = os.path.join(settings.BASE_DIR, "hello/static/hello/data/optimized_routes_example.geojson")
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
                    last_step["endLocation"]["latLng"] = {"latitude": address_coords[0], "longitude": address_coords[1]}
                    last_step["transitDetails"]["stopDetails"]["arrivalTime"] = return_time.isoformat()
                leg["duration"] = "7200s"
            resp = travel_back

        else:
            # --- APPEL RÉEL À L'API GOOGLE ---
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
                time.sleep(0.05)  
                continue

            resp = r.json()

        # --- TRAITEMENT DU RÉSULTAT ---
        steps = resp.get("routes", [{}])[0].get("legs", [{}])[0].get("steps", [])
        transit_steps = [s for s in steps if s.get("travelMode") == "TRANSIT"]

        if transit_steps:
            # --- Vérifier que l'itinéraire est bien le bon jour ---
            target_day = return_time.date()
            if not _is_itinerary_on_target_day(resp, target_day):
                print(f" ❌ Itinéraire retour trouvé depuis {stop_id}, mais pas le bon jour.")
                time.sleep(0.05)
                continue
            
            print(f" ✅ Itinéraire retour trouvé depuis l'arrêt {stop_id}.")
            # Reset compteur si succès
            stops_data[stop_id]["failure_count"] = 0
            return_transit_route = resp
            first_step_start = transit_steps[0]["startLocation"]["latLng"]
            break
        else:
            print(f" ⚠ Aucun transit trouvé depuis l'arrêt {stop_id}.")
            # Incrément compteur
            stop_info = stops_data.get(stop_id, {})
            stop_info["failure_count"] = stop_info.get("failure_count", 0) + 1
            print(f" ⚠ Compteur échec pour {stop_id} = {stop_info['failure_count']}")
            # Suppression si compteur >= 20
            if stop_info["failure_count"] >= 20:
                print(f" ❌ Suppression définitive de l'arrêt {stop_id}")
                stops_data.pop(stop_id)
            time.sleep(0.05)

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
