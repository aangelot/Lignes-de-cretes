"""
Calcul de l'itinéraire de transport en commun retour.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings

logger = logging.getLogger(__name__)

from ..utils.geotools import haversine, geocode_address
from ..utils.maps_tools import call_maps_routes_api
from .transit_go import coords_from_station_label
from .progress import update_status
from hello.constants import TRANSIT_WEIGHTS, TRANSIT_FAILURE_THRESHOLD, RETURN_STOP_MAX_DISTANCE_RATIO


def choose_return_stop(departure_stop_info, stops_data, distance_max_m, transit_priority="balanced"):
    """
    Choisit un arrêt retour plausible en privilégiant les distances plus élevées.

    Logique par tranches :
    - Tranche 1 : 50-75% de distance max, triée par tc_score
    - Tranche 2 : 25-50% de distance max, triée par tc_score
    - Tranche 3 : 0-25% de distance max, triée par tc_score
    - Tranche 4 : 75-100% de distance max, triée par tc_score
    """
    weights = TRANSIT_WEIGHTS.get(transit_priority, TRANSIT_WEIGHTS["balanced"])
    departure_coord = tuple(departure_stop_info["node"])
    max_return_dist = distance_max_m * RETURN_STOP_MAX_DISTANCE_RATIO

    tranches = [
        (1, 0.50 * max_return_dist, 0.75 * max_return_dist),
        (2, 0.25 * max_return_dist, 0.50 * max_return_dist),
        (3, 0.0,                    0.25 * max_return_dist),
        (4, 0.75 * max_return_dist, max_return_dist),
    ]

    all_candidates = []
    for priority, dist_min, dist_max in tranches:
        candidates = []
        for stop_id, stop_info in stops_data.items():
            stop_coord = tuple(stop_info["node"])
            dist = haversine(
                (departure_coord[1], departure_coord[0]),
                (stop_coord[1], stop_coord[0]),
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
        candidates.sort(key=lambda x: x[1], reverse=True)
        all_candidates.extend(candidates)

    if not all_candidates:
        raise RuntimeError("Aucun arrêt retour plausible trouvé")

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
    logger.info(
        f"Arrêts retour classés. Premier candidat : {best['stop_id']} "
        f"(tc_score={best['tc_score']:.3f}, distance={best['dist']:.0f} m)"
    )
    return ranked


def _validate_return_transit_date(transit_steps, return_time, departure_time, return_duration_seconds):
    """
    Valide le timing du trajet retour :
    - Normalement le trajet doit commencer le jour du retour.
    - Exception : la veille est acceptée si trek >= 5 jours ET retour >= 10h.
    """
    if not transit_steps:
        return

    requested_return_date = return_time.date()
    trek_start_date = departure_time.date()

    first_departure_str = (
        transit_steps[0].get("transitDetails", {}).get("stopDetails", {}).get("departureTime")
    )
    if not first_departure_str:
        return

    first_departure = (
        datetime.fromisoformat(first_departure_str.replace("Z", "+00:00"))
        .astimezone(ZoneInfo("Europe/Paris"))
    )
    departure_date = first_departure.date()

    if departure_date == requested_return_date:
        return

    if departure_date == requested_return_date - timedelta(days=1):
        trek_calendar_days = (requested_return_date - trek_start_date).days + 1
        if trek_calendar_days >= 5 and return_duration_seconds / 3600.0 >= 10:
            return

    raise RuntimeError(
        f"Trajet retour invalide : départ {first_departure.isoformat()}, "
        f"date demandée {requested_return_date}. "
        f"Le trajet doit commencer le {requested_return_date}. "
        f"(Exception : veille possible seulement si trek >= 5 jours ET retour >= 10h)"
    )


def get_transit_route_for_stop(return_stop_info, return_time, address, departure_time=None):
    """Renvoie la réponse Google et la durée retour (en secondes) pour un arrêt donné."""
    stop_coord = tuple(return_stop_info["node"])
    address_coords = coords_from_station_label(address) or geocode_address(address)

    resp = call_maps_routes_api(
        origin_latlon=(stop_coord[1], stop_coord[0]),
        destination_latlon=address_coords,
        arrival_time=return_time,
    )

    steps = resp.get("routes", [{}])[0].get("legs", [{}])[0].get("steps", [])
    transit_steps = [s for s in steps if s.get("travelMode") == "TRANSIT"]

    if not transit_steps:
        raise RuntimeError("Aucun step TRANSIT pour retour")

    duration_sec = int(resp["routes"][0]["legs"][0]["duration"].replace("s", ""))

    if departure_time:
        _validate_return_transit_date(transit_steps, return_time, departure_time, duration_sec)

    return resp, duration_sec


def compute_return_transit(
    return_candidates, return_time, address,
    stops_data=None, departure_time=None, status_callback=None
):
    """
    Teste le classement des arrêts retour et renvoie le premier itinéraire TC valide.
    Retourne : (candidate, transit_response, duration_seconds)
    """
    if not return_candidates:
        raise RuntimeError("Aucun candidat d'arrêt retour fourni")

    last_exception = None
    for candidate in return_candidates:
        stop_info = candidate.get("stop_info")
        stop_id = candidate.get("stop_id")
        update_status("Tentative d'itinéraire de retour", status_callback, 60)
        try:
            resp, duration_sec = get_transit_route_for_stop(
                stop_info, return_time, address, departure_time=departure_time
            )
            stop_info["failure_count"] = 0
            update_status("Retour transport en commun valide trouvé", status_callback)
            return candidate, resp, duration_sec
        except Exception as exc:
            last_exception = exc
            update_status("Tests de plusieurs arrêts pour le trajet retour...", status_callback, 60)
            stop_info["failure_count"] = stop_info.get("failure_count", 0) + 1
            logger.warning(f"Compteur échec pour {stop_id} = {stop_info['failure_count']}")
            if stops_data and stop_info["failure_count"] >= TRANSIT_FAILURE_THRESHOLD:
                logger.warning(f"Suppression définitive de l'arrêt {stop_id}")
                stops_data.pop(stop_id, None)
            continue

    raise RuntimeError(
        "Aucun itinéraire de retour trouvé parmi les candidats"
        + (f" ({last_exception})" if last_exception else "")
    )
