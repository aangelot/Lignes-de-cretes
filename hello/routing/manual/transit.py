"""
Trajets en transport en commun vers / depuis un arrêt choisi par l'utilisateur.

Contrairement au mode automatique, on n'itère pas sur des candidats : l'arrêt est
imposé, on fait un seul appel Google. Les contraintes horaires du mode automatique
ne sont pas éliminatoires ici, elles deviennent des alertes affichées à
l'utilisateur, qui reste libre de continuer.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from hello.constants import (
    MINIMAL_WALK_HOURS,
    MAX_DEPARTURE_DELAY_DAY_HOURS,
    MAX_DEPARTURE_DELAY_EVENING_HOURS,
)
from hello.routing.domain.transit_go import coords_from_station_label
from hello.routing.domain.transit_back import get_transit_route_for_stop
from hello.routing.utils.maps_tools import call_maps_routes_api
from .stops import load_stops

logger = logging.getLogger(__name__)

PARIS = ZoneInfo("Europe/Paris")


class NoTransitFound(Exception):
    """Aucun trajet en transport en commun pour l'arrêt demandé : en choisir un autre."""


def _as_paris(dt):
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.replace(tzinfo=PARIS) if dt.tzinfo is None else dt


def _transit_steps(response):
    leg = response.get("routes", [{}])[0].get("legs", [{}])[0]
    return [s for s in leg.get("steps", []) if s.get("travelMode") == "TRANSIT"]


def _stop_time(step, key):
    raw = step["transitDetails"]["stopDetails"][key]
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(PARIS)


def _format_delta(delta):
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes // 60} h {minutes % 60:02d}"


def _go_warnings(transit_steps, departure_time, return_time):
    """Mêmes règles que get_best_transit_route, formulées en alertes."""
    warnings = []
    dep_time = _stop_time(transit_steps[0], "departureTime")
    arrival_time = _stop_time(transit_steps[-1], "arrivalTime")

    max_delay_h = (
        MAX_DEPARTURE_DELAY_EVENING_HOURS if departure_time.hour >= 18
        else MAX_DEPARTURE_DELAY_DAY_HOURS
    )
    delay = dep_time - departure_time
    if delay > timedelta(hours=max_delay_h):
        warnings.append(
            f"Premier départ possible le {dep_time.strftime('%d/%m à %H:%M')}, "
            f"soit {_format_delta(delay)} après l'heure souhaitée."
        )

    # Même approximation qu'en mode automatique : le retour dure autant que l'aller.
    remaining_walk = (return_time - arrival_time) - (arrival_time - dep_time)
    if remaining_walk < timedelta(hours=MINIMAL_WALK_HOURS):
        warnings.append(
            f"Arrivée à {arrival_time.strftime('%H:%M')} : il resterait environ "
            f"{_format_delta(max(remaining_walk, timedelta(0)))} de marche avant le retour "
            f"(moins de {MINIMAL_WALK_HOURS} h)."
        )
    return warnings


def compute_go_for_stop(massif, stop_id, address, departure_time, return_time):
    """
    Trajet aller gare → arrêt `stop_id`.

    Retourne {"transit_go": réponse Google, "stop": {...}, "warnings": [...]}.
    Lève NoTransitFound si Google ne propose aucun trajet en transport en commun.
    """
    departure_time = _as_paris(departure_time)
    return_time = _as_paris(return_time)

    stop_info = load_stops(massif).get(str(stop_id))
    if stop_info is None:
        raise ValueError(f"Arrêt inconnu : {stop_id}")

    address_coords = coords_from_station_label(address)
    if not address_coords:
        raise ValueError(f"Gare de départ introuvable : '{address}'")

    lon, lat = stop_info["node"][0], stop_info["node"][1]
    response = call_maps_routes_api(
        origin_latlon=address_coords,
        destination_latlon=(lat, lon),
        departure_time=departure_time,
    )

    transit_steps = _transit_steps(response)
    if not transit_steps:
        logger.info(f"Mode manuel : aucun trajet aller vers l'arrêt {stop_id} ({massif})")
        raise NoTransitFound(
            "Aucun trajet en transport en commun trouvé vers cet arrêt pour cette date."
        )

    last = transit_steps[-1]["transitDetails"]["stopDetails"]
    return {
        "transit_go": response,
        "stop": {
            "id": str(stop_id),
            "lon": lon,
            "lat": lat,
            # Nom du fichier d'arrêts ; à défaut, dernier arrêt desservi selon Google
            "name": stop_info["properties"].get("stop_name") or last.get("arrivalStop", {}).get("name"),
        },
        "warnings": _go_warnings(transit_steps, departure_time, return_time),
    }


def compute_back_for_stop(massif, stop_id, address, departure_time, return_time):
    """
    Trajet retour arrêt `stop_id` → gare, pour arriver avant `return_time`.

    Reprend la validation du mode automatique (départ le jour du retour, sauf trek
    long). Retourne {"transit_back": réponse Google, "stop": {...}}.
    Lève NoTransitFound si aucun trajet ne convient.
    """
    departure_time = _as_paris(departure_time)
    return_time = _as_paris(return_time)

    stop_info = load_stops(massif).get(str(stop_id))
    if stop_info is None:
        raise ValueError(f"Arrêt inconnu : {stop_id}")

    try:
        response, _ = get_transit_route_for_stop(
            stop_info, return_time, address, departure_time=departure_time
        )
    except RuntimeError as exc:
        logger.info(f"Mode manuel : pas de retour depuis l'arrêt {stop_id} ({massif}) : {exc}")
        if str(exc).startswith("Trajet retour invalide"):
            raise NoTransitFound(
                "Depuis cet arrêt, il faudrait partir avant le jour du retour. "
                "Choisissez un autre arrêt ou modifiez la date de retour."
            )
        raise NoTransitFound(
            "Aucun trajet en transport en commun depuis cet arrêt pour arriver le "
            f"{return_time.strftime('%d/%m avant %H:%M')}. Choisissez un autre arrêt."
        )

    first = _transit_steps(response)[0]["transitDetails"]["stopDetails"]
    lon, lat = stop_info["node"][0], stop_info["node"][1]
    return {
        "transit_back": response,
        "stop": {
            "id": str(stop_id),
            "lon": lon,
            "lat": lat,
            "name": stop_info["properties"].get("stop_name") or first.get("departureStop", {}).get("name"),
            "departure_time": first.get("departureTime"),
        },
    }
