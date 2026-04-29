"""
Gestion des itinéraires de transport en commun (aller/retour).
"""

import json
import os
import random
import time
import requests
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from django.conf import settings
from networkx import shortest_path
from .geotools import geocode_address, haversine, find_nearest_node
from hello.management.commands.utils import normalize_label
from hello.constants import TRANSIT_WEIGHTS, TRANSIT_FAILURE_THRESHOLD, MINIMAL_WALK_HOURS, MAX_DEPARTURE_DELAY_DAY_HOURS, MAX_DEPARTURE_DELAY_EVENING_HOURS, RETURN_STOP_MAX_DISTANCE_RATIO

# Charger la clé API Google
from dotenv import load_dotenv
load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_API_KEY")


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

    target = normalize_label(label)
    if not target:
        return None

    for feat in data.get("features", []):
        props = feat.get("properties", {}) or {}
        lib = props.get("libelle") or props.get("name") or ""
        if normalize_label(lib) == target:
            coords = feat.get("geometry", {}).get("coordinates")
            if coords and len(coords) >= 2:
                # GeoJSON coords: [lon, lat] -> return (lat, lon)
                return (coords[1], coords[0])
    return None


def get_best_transit_route(randomness=0.1, departure_time=None, return_time=None,
                           stops_data=None, address='', transit_priority="balanced", hubs_entree_data=None):
    """
    Sélectionne le meilleur arrêt selon le score et récupère un itinéraire de transport en commun via Google Maps.
    Ajoute des règles temporelles :
    - Départ matin/journée : max +6h
    - Départ soir (>18h) : max +18h
    - Vérifie que l'arrivée sur place laisse au moins 4h de marche avant le retour
    """
    # Tenter de récupérer les coordonnées à partir du libellé de gare (fallback geocoding)
    address_coords = _coords_from_station_label(address)

    # Choisir le hub de départ le plus proche
    hubs_departs = []
    try:
        hubs_departs_path = os.path.join(settings.BASE_DIR, "data", "input", "hubs_departs.geojson")
        with open(hubs_departs_path, "r", encoding="utf-8") as hf:
            hubs_departs = json.load(hf).get("features", [])
    except Exception:
        hubs_departs = []

    ## Charger les hubs d'entrée du massif sélectionné et les ajouter aux hubs de départ
    hubs_entree_features = hubs_entree_data.get("features", [])
    hubs_departs.extend(hubs_entree_features)

    ## Trouver le hub de départ le plus proche de la station de départ 
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
        ## Trouver le hub d'entrée correspondant à ce stop
        for hf in hubs_entree_features:
            hid = hf.get("properties", {}).get("id") or hf.get("properties", {}).get("nom")
            if hid == hub_entree_id:
                matched = hf
                break
        ## Si on a trouvé le hub d'entrée, tenter de récupérer la durée hub_depart -> hub_entree
        if matched:
            dur_map = matched.get("properties", {}).get("durations_from_hubs", {})
            if departure_hub_name and isinstance(dur_map, dict):
                dur_hub_to_hub_entree = float(dur_map.get(departure_hub_name, 10000))
        ## Ensuite, trouver la durée hub_entree -> stop
        if "duration" in props and props.get("duration") is not None:
            dur_hub_entree_to_stop = float(props.get("duration"))
        elif "duration_min_go" in props and props.get("duration_min_go") is not None:
            dur_hub_entree_to_stop = float(props.get("duration_min_go"))
        else:
            dur_hub_entree_to_stop = 10000.0
        ## Somme des deux durées pour obtenir une estimation du temps total de transport en commun jusqu'au stop
        total_min = dur_hub_to_hub_entree + dur_hub_entree_to_stop
        props["duration_min_go"] = total_min
        duration_values.append(total_min)

    # Normaliser les durations pour le scoring
    minv = min(duration_values)
    maxv = max(duration_values)
    for stop_id, stop_info in (stops_data or {}).items():
        props = stop_info.setdefault("properties", {})
        val = props.get("duration_min_go")
        if val is None:
            props["duration_min_go_normalized"] = 1.0
        else:
            props["duration_min_go_normalized"] = (val - minv) / (maxv - minv)


    weights = TRANSIT_WEIGHTS.get(transit_priority, TRANSIT_WEIGHTS["balanced"])

    # Scorer les arrêts et trier
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

    # --- Reprise mode normal ---

    # Tenter de trouver un itinéraire de transport en commun valide parmi les stops scorés
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

                if stop_info["failure_count"] >= TRANSIT_FAILURE_THRESHOLD:
                    print(f"❌ Suppression définitive de l'arrêt {stop_id}")
                    stops_data.pop(stop_id)

                time.sleep(0.05)
                continue
            
            else:
                stop_info["failure_count"] = 0

            dep_time_str = transit_steps[0]["transitDetails"]["stopDetails"]["departureTime"]
            dep_time = datetime.fromisoformat(dep_time_str).astimezone(ZoneInfo("Europe/Paris"))

            # Par rapport à la date de départ souhaitée, vérifier que le départ n'est pas trop tard...
            max_delay_h = MAX_DEPARTURE_DELAY_EVENING_HOURS if departure_time.hour >= 18 else MAX_DEPARTURE_DELAY_DAY_HOURS

            if not (dep_time - departure_time) <= timedelta(hours=max_delay_h):
                print(f"⏰ Départ trop éloigné ({dep_time - departure_time}), on ignore {stop_id}")
                continue

            arrival_time_str = transit_steps[-1]["transitDetails"]["stopDetails"]["arrivalTime"]
            arrival_time = datetime.fromisoformat(arrival_time_str).astimezone(ZoneInfo("Europe/Paris"))
            est_travel_duration = arrival_time - dep_time

            # Vérifier que le temps restant pour la marche est suffisant (on considère le temps du retour en TC égal au trajet aller à ce stade)
            remaining_walk_time = (return_time - arrival_time) - est_travel_duration 
            if remaining_walk_time.total_seconds() < MINIMAL_WALK_HOURS * 3600:
                print(f"🚫 Trajet vers {stop_id} laisse trop peu de temps de marche (temps de marche <{MINIMAL_WALK_HOURS}h)")
                continue
            
            # Si on arrive ici, c'est que l'itinéraire de transport en commun est valide selon les règles temporelles définies
            print(f"✅ Itinéraire valide trouvé depuis l'arrêt {stop_id} (score={score_final:.3f})")
            
            return data, stop_id, stop_info

        except Exception as e:
            time.sleep(0.05)
            print(f"⚠️ Tentative échouée pour l'arrêt {stop_id} ({score_final:.3f}): {e}")
            continue

    raise RuntimeError("Aucun itinéraire de transport en commun trouvé respectant les contraintes temporelles")

  
def choose_return_stop(
    departure_stop_info,
    stops_data,
    distance_max_m,
    transit_priority="balanced"
):
    """
    Choisit un arrêt retour plausible en privilégiant les distances plus élevées.

    Logique par tranches :
    - Tranche 1 : 50-75% de distance max, triée par tc_score
    - Tranche 2 : 25-50% de distance max, triée par tc_score
    - Tranche 3 : 0-25% de distance max, triée par tc_score
    Sélectionne le meilleur arrêt dans l'ordre des tranches.
    """

    weights = TRANSIT_WEIGHTS.get(transit_priority, TRANSIT_WEIGHTS["balanced"])

    departure_coord = tuple(departure_stop_info["node"])

    max_return_dist = distance_max_m * RETURN_STOP_MAX_DISTANCE_RATIO

    # Définir les tranches avec priorité (1 = haute, 3 = basse)
    tranches = [
        (1, "tranche1", 0.50 * max_return_dist, 0.75 * max_return_dist),
        (2, "tranche2", 0.25 * max_return_dist, 0.50 * max_return_dist),
        (3, "tranche3", 0.0, 0.25 * max_return_dist),
        (4, "tranche4", 0.75 * max_return_dist, max_return_dist)
    ]

    all_candidates = []

    for priority, tranche_name, dist_min, dist_max in tranches:
        candidates = []

        for stop_id, stop_info in stops_data.items():
            stop_coord = tuple(stop_info["node"])

            dist = haversine(
                (departure_coord[1], departure_coord[0]),
                (stop_coord[1], stop_coord[0])
            )

            if not (dist_min <= dist <= dist_max):
                continue

            props = stop_info.get("properties", {})

            tc_score = (
                weights["duration"] * (1 - props.get("duration_min_go_normalized", 0))
                + weights["elevation"] * props.get("elevation_normalized", 0)
                + weights["nature"] * props.get("distance_to_pnr_border_normalized", 0)
            )

            candidates.append((priority, tc_score, stop_id, stop_info, dist))

        # Trier cette tranche par tc_score décroissant
        candidates.sort(key=lambda x: x[1], reverse=True)

        all_candidates.extend(candidates)

    if not all_candidates:
        raise RuntimeError("Aucun arrêt retour plausible trouvé")

    # Trier globalement : d'abord par priorité (1,2,3), puis par tc_score décroissant
    all_candidates.sort(key=lambda x: (x[0], -x[1]))

    ranked = [
        {
            "score": tc_score,
            "stop_id": stop_id,
            "stop_info": stop_info,
            "dist": dist,
            "tc_score": tc_score,
            "dist_score": dist / max_return_dist if max_return_dist > 0 else 0,
        }
        for priority, tc_score, stop_id, stop_info, dist in all_candidates
    ]

    best = ranked[0]

    print(
        f"Arrêts retour classés. Premier candidat : {best['stop_id']} "
        f"(tc_score={best['tc_score']:.3f}, distance={best['dist']:.0f} m)"
    )

    return ranked




def _validate_return_transit_date(transit_steps, return_time, departure_time, return_duration_seconds):
    """
    Valide le timing du trajet retour selon les règles :
    1. Normalement, le trajet retour doit commencer le jour du retour (return_time)
    2. Exception : un trajet commençant la veille est accepté UNIQUEMENT si :
       - Le trek a duré 5 jours ou plus (return_time - departure_time >= 5 jours)
       - ET le trajet retour dure plus de 10 heures
    
    Args:
        transit_steps: Liste des steps TRANSIT de la réponse Google
        return_time: datetime du jour demandé pour le retour
        departure_time: datetime du début du trek
        return_duration_seconds: durée totale du trajet retour en secondes
    
    Raises:
        RuntimeError si le trajet retour ne respecte pas les règles
    """
    if not transit_steps:
        return
    
    # Extraire la date demandée et la date de départ
    requested_return_date = return_time.date()
    trek_start_date = departure_time.date()
    
    # Extraire le début du trajet retour (premier step TRANSIT)
    first_step = transit_steps[0]
    first_departure_str = first_step.get("transitDetails", {}).get("stopDetails", {}).get("departureTime")
    
    if not first_departure_str:
        # Si on n'a pas les infos de timing, on accepte (cas de mock ou données incomplètes)
        return
    
    # Parser le timestamp ISO 8601 avec timezone
    first_departure = datetime.fromisoformat(first_departure_str.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Paris"))
    departure_date = first_departure.date()
    
    # Règle 1 : Le trajet retour doit commencer le jour demandé
    if departure_date == requested_return_date:
        return
    
    # Règle 2 : Exception pour un trajet commençant la veille
    if departure_date == requested_return_date - timedelta(days=1):
        # Calculer le nombre de jours calendaires du trek (inclusif des deux extrêmes)
        trek_calendar_days = (requested_return_date - trek_start_date).days + 1
        return_duration_hours = return_duration_seconds / 3600.0
        
        # Conditions pour accepter la veille :
        # - Trek >= 5 jours calendaires
        # - Trajet retour >= 10 heures
        if trek_calendar_days >= 5 and return_duration_hours >= 10:
            return
    
    # Trajet non valide
    raise RuntimeError(
        f"Trajet retour invalide : départ {first_departure.isoformat()}, "
        f"date demandée {requested_return_date}. "
        f"Le trajet doit commencer le {requested_return_date}. "
        f"(Exception : veille possible seulement si trek >= 5 jours ET retour >= 10h)"
    )


def get_transit_route_for_stop(return_stop_info, return_time, address, departure_time=None):
    """Renvoie la réponse Google et durée retour (en secondes) pour un arrêt donné.
    
    Args:
        return_stop_info: Info du point retour
        return_time: Datetime du retour demandé
        address: Adresse de départ
        departure_time: Datetime du début du trek (optionnel, pour validation avancée)
    """

    stop_coord = tuple(return_stop_info["node"])

    origin = {
        "location": {
            "latLng": {
                "latitude": stop_coord[1],
                "longitude": stop_coord[0]
            }
        }
    }

    address_coords = _coords_from_station_label(address) or geocode_address(address)

    destination = {
        "location": {
            "latLng": {
                "latitude": address_coords[0],
                "longitude": address_coords[1]
            }
        }
    }

    if getattr(settings, "USE_MOCK_ROUTE_CREATION", False):
        file_path = os.path.join(settings.BASE_DIR, "hello/static/hello/data/optimized_routes_example.geojson")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        resp = data["features"][0]["properties"].get("transit_back")

        if not resp:
            raise RuntimeError("Aucun itinéraire mock retour trouvé")

        duration_str = resp["routes"][0]["legs"][0]["duration"]
        duration_sec = int(duration_str.replace("s", ""))
        return resp, duration_sec

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
    r.raise_for_status()

    resp = r.json()
    steps = resp.get("routes", [{}])[0].get("legs", [{}])[0].get("steps", [])
    transit_steps = [s for s in steps if s.get("travelMode") == "TRANSIT"]

    if not transit_steps:
        raise RuntimeError("Aucun step TRANSIT pour retour")

    duration_str = resp["routes"][0]["legs"][0]["duration"]
    duration_sec = int(duration_str.replace("s", ""))

    # Valider le timing du trajet retour
    if departure_time:
        _validate_return_transit_date(transit_steps, return_time, departure_time, duration_sec)

    return resp, duration_sec


def compute_return_transit(return_candidates, return_time, address, stops_data=None, departure_time=None):
    """
    Teste le classement des arrêts retour et renvoie le premier itinéraire TC valide.

    Args:
        return_candidates: Liste des candidats d'arrêt retour
        return_time: Datetime du retour demandé
        address: Adresse de départ
        stops_data: Données des arrêts (optionnel)
        departure_time: Datetime du début du trek (optionnel, pour validation)
    
    Returns : (candidate, transit_response, duration_seconds)
    """

    if not return_candidates:
        raise RuntimeError("Aucun candidat d'arrêt retour fourni")

    last_exception = None
    for candidate in return_candidates:
        stop_info = candidate.get("stop_info")
        stop_id = candidate.get("stop_id")
        try:
            resp, duration_sec = get_transit_route_for_stop(stop_info, return_time, address, departure_time=departure_time)
            # Réussite : réinitialiser le failure_count
            stop_info["failure_count"] = 0
            return candidate, resp, duration_sec
        except Exception as exc:
            last_exception = exc
            # Échec : incrémenter le failure_count
            stop_info["failure_count"] = stop_info.get("failure_count", 0) + 1
            print(f"⚠️ Compteur échec pour {stop_id} = {stop_info['failure_count']}")

            if stops_data and stop_info["failure_count"] >= TRANSIT_FAILURE_THRESHOLD:
                print(f"❌ Suppression définitive de l'arrêt {stop_id}")
                stops_data.pop(stop_id, None)
            continue

    raise RuntimeError(
        "Aucun itinéraire de retour trouvé parmi les candidats" +
        (f" ({last_exception})" if last_exception else "")
    )
