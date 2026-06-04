"""
Orchestration principale : charge les données, choisit le mode, délègue, finalise.
"""

import json
import logging
from datetime import datetime
from hello.data_preparation.utils import slugify

logger = logging.getLogger(__name__)

from .utils.files_tools import load_massif_data, build_geojson, save_result
from .domain.transit_go import get_best_transit_route
from .domain.route_init import initialize_route_parameters
from .domain.elevation import get_elevations, smooth_elevations, compute_total_ascent
from .domain.progress import update_status
from .domain.route_crossing_or_loop import compute_crossing_route
from .domain.route_massif_tour import compute_massif_tour_route
from .domain.route_poi import compute_poi_route


def _dispatch_route(pois, massif, massif_clean, departure_time, return_time, level,
                    address, transit_priority, randomness, stops_data, G, poi_data,
                    hubs_entree_data, status_callback):
    """Choisit le mode de calcul et retourne route_data standardisé."""
    # Mode de calcul de type POI
    if pois:
        update_status("Calcul du chemin avec les points d'intérêt", status_callback, 10)
        return compute_poi_route(
            randomness=randomness, massif=massif,
            departure_time=departure_time, return_time=return_time,
            level=level, address=address, transit_priority=transit_priority,
            pois=pois, stops_data=stops_data, G=G, poi_data=poi_data,
            hubs_entree_data=hubs_entree_data, status_callback=status_callback,
        )

    # Mode de calcul de type tour massif ou traversée
    update_status("Calcul du transport aller", status_callback, 15)
    travel_go, departure_stop_id, departure_stop_info = get_best_transit_route(
        randomness=randomness, departure_time=departure_time, return_time=return_time,
        stops_data=stops_data, address=address, transit_priority=transit_priority,
        hubs_entree_data=hubs_entree_data,
    )
    update_status("Point de départ déterminé", status_callback, 25)

    max_distance_m, route_type = initialize_route_parameters(
        massif_name=massif, departure_time=departure_time, return_time=return_time,
        level=level, transit_route=travel_go,
    )
    logger.info(f"Distance max : {max_distance_m/1000:.1f} km | Route type : {route_type}")

    if route_type == "crossing":
        route_data = compute_crossing_route(
            departure_stop_info=departure_stop_info, departure_stop_id=departure_stop_id,
            massif=massif, massif_clean=massif_clean, max_distance_m=max_distance_m,
            G=G, poi_data=poi_data, stops_data=stops_data, randomness=randomness,
            travel_go=travel_go, departure_time=departure_time, return_time=return_time,
            level=level, transit_priority=transit_priority, address=address,
            status_callback=status_callback,
        )
    elif route_type == "massif_tour":
        route_data = compute_massif_tour_route(
            departure_stop_info=departure_stop_info, max_distance_m=max_distance_m,
            massif_clean=massif_clean, G=G, poi_data=poi_data, stops_data=stops_data,
            randomness=randomness, departure_time=departure_time, return_time=return_time,
            address=address, transit_priority=transit_priority, status_callback=status_callback,
        )
    else:
        raise ValueError(f"route_type inconnu : {route_type}")

    route_data["travel_go"] = travel_go
    route_data["route_type"] = route_type
    return route_data


def compute_best_route(
    randomness=0.2,
    massif="Chartreuse",
    departure_time: datetime = None,
    return_time: datetime = None,
    level: str = "intermediaire",
    address: str = "",
    transit_priority: str = "balanced",
    pois=None,
    status_callback=None,
):
    # Étape 1 : Chargement des données du massif
    massif_clean = slugify(massif)
    massif_data = load_massif_data(massif)
    stops_data = massif_data["stops_data"]
    stops_path = massif_data["stops_path"]
    G = massif_data["G"]
    poi_data = massif_data["poi_data"]
    hubs_entree_data = massif_data["hubs_entree_data"]
    update_status("Données du massif chargées", status_callback, 5)

    departure_time = datetime.fromisoformat(departure_time)
    return_time = datetime.fromisoformat(return_time)

    # Étape 2 : Calcul du chemin optimal selon le mode (POI, tour massif, traversée)
    route_data = _dispatch_route(
        pois=pois, massif=massif, massif_clean=massif_clean,
        departure_time=departure_time, return_time=return_time,
        level=level, address=address, transit_priority=transit_priority,
        randomness=randomness, stops_data=stops_data, G=G, poi_data=poi_data,
        hubs_entree_data=hubs_entree_data, status_callback=status_callback,
    )

    path = route_data.get("path") or []
    dist = route_data.get("dist") or 0
    logger.info(f"Distance randonnée finale : {dist/1000:.1f} km")

    # Étape 3 : Calcul des altitudes 
    update_status("Calcul des altitudes", status_callback, 90)
    if not path:
        smoothed_elevations, total_ascent, elevation_failed = [], 0, True
    else:
        elevations = get_elevations(path)
        elevation_failed = all(ele == 0 for ele in elevations)
        smoothed_elevations = smooth_elevations(elevations, window=9)
        total_ascent = compute_total_ascent(smoothed_elevations)

    # Etape 4 : Construction du GeoJSON final et sauvegarde
    path = [[lon, lat, round(ele)] for (lon, lat), ele in zip(path, smoothed_elevations)]

    result = build_geojson(
        path=path, dist=dist,
        route_type=route_data["route_type"],
        travel_go=route_data["travel_go"],
        travel_return=route_data["travel_return"],
        total_ascent=total_ascent,
        elevation_failed=elevation_failed,
        return_error_message=route_data.get("return_error_message"),
        poi_data=poi_data,
    )

    save_result(result, address, massif_clean, level, randomness, status_callback)

    # Etape 5 : Sauvegarde des compteurs d'échec pour les arrêts de transport en commun
    try:
        with open(stops_path, "w", encoding="utf-8") as f:
            json.dump(stops_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Erreur sauvegarde compteurs d'échec : {e}")

    return result
