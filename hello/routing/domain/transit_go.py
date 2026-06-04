"""
Calcul de l'itinéraire de transport en commun aller.
"""

import json
import logging
import os
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings

logger = logging.getLogger(__name__)

from ..utils.geotools import haversine
from ..utils.maps_tools import call_maps_routes_api
from hello.data_preparation.utils import normalize_label
from hello.constants import (
    TRANSIT_WEIGHTS, TRANSIT_FAILURE_THRESHOLD,
    MINIMAL_WALK_HOURS, MAX_DEPARTURE_DELAY_DAY_HOURS, MAX_DEPARTURE_DELAY_EVENING_HOURS,
)


def coords_from_station_label(label):
    """
    Cherche dans data/input/liste-des-gares.geojson une gare correspondant au libellé `label`.
    Retourne (lat, lon) si trouvée, sinon None.
    """
    try:
        gj_path = os.path.join(settings.BASE_DIR, "data", "input", "liste-des-gares.geojson")
        with open(gj_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        logger.warning(f"Impossible de lire liste-des-gares.geojson : {e}")
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
                return (coords[1], coords[0])
    return None


def _find_nearest_hub(address_coords, hubs_departs):
    """Retourne le nom du hub de départ le plus proche de address_coords (lat, lon)."""
    best = None
    for hf in hubs_departs:
        hub_coords = hf.get("geometry", {}).get("coordinates")
        if not hub_coords:
            continue
        d = haversine((address_coords[0], address_coords[1]), (hub_coords[1], hub_coords[0]))
        if best is None or d < best[0]:
            best = (d, hf)
    return best[1].get("properties", {}).get("nom") or best[1].get("properties", {}).get("id")


def _compute_and_normalize_durations(stops_data, hubs_entree_features, departure_hub_name):
    """
    Calcule duration_min_go (hub_départ→hub_entrée + hub_entrée→stop) pour chaque stop
    et normalise entre 0 et 1.
    """
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
            dur_hub_entree_to_stop = float(props["duration"])
        elif "duration_min_go" in props and props.get("duration_min_go") is not None:
            dur_hub_entree_to_stop = float(props["duration_min_go"])
        else:
            dur_hub_entree_to_stop = 10000.0

        total_min = dur_hub_to_hub_entree + dur_hub_entree_to_stop
        props["duration_min_go"] = total_min
        duration_values.append(total_min)

    if not duration_values:
        return stops_data

    minv = min(duration_values)
    maxv = max(duration_values)
    for stop_id, stop_info in (stops_data or {}).items():
        props = stop_info.setdefault("properties", {})
        val = props.get("duration_min_go")
        if val is None:
            props["duration_min_go_normalized"] = 1.0
        elif maxv == minv:
            props["duration_min_go_normalized"] = 0.0
        else:
            props["duration_min_go_normalized"] = (val - minv) / (maxv - minv)

    return stops_data


def _score_stops(stops_data, transit_priority, randomness):
    """Calcule les scores et retourne la liste triée (score_final, stop_id, stop_info)."""
    weights = TRANSIT_WEIGHTS.get(transit_priority, TRANSIT_WEIGHTS["balanced"])
    scored = []
    for stop_id, stop_info in stops_data.items():
        props = stop_info.get("properties", {})
        score = (
            weights["duration"] * (1 - props.get("duration_min_go_normalized", 0))
            + weights["elevation"] * props.get("elevation_normalized", 0)
            + weights["nature"] * props.get("distance_to_pnr_border_normalized", 0)
        )
        score_final = (1 - randomness) * score + randomness * random.random()
        scored.append((score_final, stop_id, stop_info))
    scored.sort(reverse=True, key=lambda x: x[0])
    return scored


def get_best_transit_route(randomness=0.1, departure_time=None, return_time=None,
                           stops_data=None, address='', transit_priority="balanced",
                           hubs_entree_data=None):
    """
    Sélectionne le meilleur arrêt selon le score et récupère un itinéraire de transport en commun via Google Maps.
    Règles temporelles :
    - Départ matin/journée : max +6h
    - Départ soir (>18h) : max +18h
    - L'arrivée sur place doit laisser au moins 4h de marche avant le retour
    """
    address_coords = coords_from_station_label(address)
    if not address_coords:
        raise RuntimeError(f"Impossible de géocoder l'adresse de départ : '{address}'")

    hubs_entree_features = hubs_entree_data.get("features", [])
    try:
        hubs_departs_path = os.path.join(settings.BASE_DIR, "data", "input", "hubs_departs.geojson")
        with open(hubs_departs_path, "r", encoding="utf-8") as hf:
            hubs_departs = json.load(hf).get("features", [])
    except Exception:
        hubs_departs = []
    hubs_departs = hubs_departs + hubs_entree_features

    departure_hub_name = _find_nearest_hub(address_coords, hubs_departs)
    logger.info(f"Hub de départ sélectionné : {departure_hub_name}")

    stops_data = _compute_and_normalize_durations(stops_data, hubs_entree_features, departure_hub_name)
    scored_stops = _score_stops(stops_data, transit_priority, randomness)

    if departure_time.tzinfo is None:
        departure_time = departure_time.replace(tzinfo=ZoneInfo("Europe/Paris"))
    if return_time.tzinfo is None:
        return_time = return_time.replace(tzinfo=ZoneInfo("Europe/Paris"))

    for score_final, stop_id, stop_info in scored_stops:
        dest_coords = stop_info["node"]
        try:
            data = call_maps_routes_api(
                origin_latlon=address_coords,
                destination_latlon=(dest_coords[1], dest_coords[0]),
                departure_time=departure_time,
            )

            leg = data.get("routes", [{}])[0].get("legs", [{}])[0]
            transit_steps = [s for s in leg.get("steps", []) if s.get("travelMode") == "TRANSIT"]

            if not transit_steps:
                logger.warning(f"Aucun step TRANSIT pour {stop_id}")
                stop_info["failure_count"] = stop_info.get("failure_count", 0) + 1
                logger.warning(f"Compteur échec pour {stop_id} = {stop_info['failure_count']}")
                if stop_info["failure_count"] >= TRANSIT_FAILURE_THRESHOLD:
                    logger.warning(f"Suppression définitive de l'arrêt {stop_id}")
                    stops_data.pop(stop_id)
                continue

            stop_info["failure_count"] = 0

            dep_time_str = transit_steps[0]["transitDetails"]["stopDetails"]["departureTime"]
            dep_time = datetime.fromisoformat(dep_time_str).astimezone(ZoneInfo("Europe/Paris"))

            max_delay_h = MAX_DEPARTURE_DELAY_EVENING_HOURS if departure_time.hour >= 18 else MAX_DEPARTURE_DELAY_DAY_HOURS
            if not (dep_time - departure_time) <= timedelta(hours=max_delay_h):
                logger.info(f"Départ trop éloigné ({dep_time - departure_time}), on ignore {stop_id}")
                continue

            arrival_time_str = transit_steps[-1]["transitDetails"]["stopDetails"]["arrivalTime"]
            arrival_time = datetime.fromisoformat(arrival_time_str).astimezone(ZoneInfo("Europe/Paris"))
            est_travel_duration = arrival_time - dep_time

            remaining_walk_time = (return_time - arrival_time) - est_travel_duration
            if remaining_walk_time.total_seconds() < MINIMAL_WALK_HOURS * 3600:
                logger.warning(f"Trajet vers {stop_id} laisse trop peu de temps de marche (<{MINIMAL_WALK_HOURS}h)")
                continue

            logger.info(f"Itinéraire valide trouvé depuis l'arrêt {stop_id} (score={score_final:.3f})")
            return data, stop_id, stop_info

        except Exception as e:
            logger.warning(f"Tentative échouée pour l'arrêt {stop_id} ({score_final:.3f}): {e}")
            continue

    raise RuntimeError("Aucun itinéraire de transport en commun trouvé respectant les contraintes temporelles")
