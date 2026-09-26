"""
Arrêts de transport en commun d'un massif, avec une durée de trajet estimée
depuis la gare de l'utilisateur.

Aucun appel externe : la durée est celle précalculée pour le mode automatique
(hub de départ le plus proche de la gare → hub d'entrée du massif → arrêt).
"""

import json
import os
import statistics

from django.conf import settings

from hello.data_preparation.utils import slugify
from hello.routing.domain.transit_go import (
    coords_from_station_label,
    _find_nearest_hub,
    _compute_and_normalize_durations,
    UNKNOWN_DURATION_MIN,
)


def _output_path(massif, suffix):
    return os.path.join(settings.BASE_DIR, "data", "output", f"{slugify(massif)}_{suffix}")


def load_stops(massif):
    """Arrêts du massif, sans charger le graphe de randonnée (trop lourd ici)."""
    with open(_output_path(massif, "arrets_stop_node_mapping.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_hubs_entree(massif):
    with open(_output_path(massif, "hubs_entree.geojson"), "r", encoding="utf-8") as fh:
        return json.load(fh).get("features", [])


def _load_hubs_departs():
    path = os.path.join(settings.BASE_DIR, "data", "input", "hubs_departs.geojson")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh).get("features", [])
    except OSError:
        return []


def get_stops_with_durations(massif, address):
    """
    Retourne les arrêts du massif et la durée estimée depuis la gare `address`.

    {
        "hub": nom du hub de départ utilisé comme approximation de la gare,
        "stats": {"min", "median", "max"} en minutes (arrêts estimables seulement),
        "stops": [{"id", "name", "lon", "lat", "elevation", "duration_min"}, ...]
    }
    `duration_min` vaut None quand le trajet n'est pas estimable.
    """
    address_coords = coords_from_station_label(address)
    if not address_coords:
        raise ValueError(f"Gare de départ introuvable : '{address}'")

    stops_data = load_stops(massif)
    hubs_entree = _load_hubs_entree(massif)
    departure_hub = _find_nearest_hub(address_coords, _load_hubs_departs() + hubs_entree)

    _compute_and_normalize_durations(stops_data, hubs_entree, departure_hub)

    stops = []
    for stop_id, info in stops_data.items():
        props = info.get("properties", {})
        duration = props.get("duration_min_go")
        if duration is None or duration >= UNKNOWN_DURATION_MIN:
            duration = None
        lon, lat = info["node"][0], info["node"][1]
        stops.append({
            "id": stop_id,
            "name": props.get("stop_name"),
            "lon": lon,
            "lat": lat,
            "elevation": props.get("elevation"),
            "duration_min": round(duration) if duration is not None else None,
        })

    known = [s["duration_min"] for s in stops if s["duration_min"] is not None]
    stats = {
        "min": min(known),
        "median": round(statistics.median(known)),
        "max": max(known),
    } if known else None

    return {"hub": departure_hub, "stats": stats, "stops": stops}
