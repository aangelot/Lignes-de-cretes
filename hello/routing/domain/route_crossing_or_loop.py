"""
Mode crossing : traversée du massif d'un arrêt aller vers un arrêt retour.
"""
import logging

from ..utils.geotools import haversine

logger = logging.getLogger(__name__)
from .transit_back import choose_return_stop, compute_return_transit
from .route_init import initialize_route_parameters
from .hiking_crossing_or_loop import best_hiking_crossing, best_hiking_loop
from .progress import update_status


def _is_loop(candidate, departure_stop_id, departure_stop_info):
    """Détermine si le candidat d'arrêt de retour implique une boucle (même arrêt ou très proche)."""
    if candidate.get("stop_id") == departure_stop_id:
        return True
    dist = haversine(departure_stop_info["node"], candidate["stop_info"]["node"])
    return dist < 5000


def _compute_hike(candidate, is_loop, departure_stop_info, massif_clean, max_distance_m, G, poi_data, randomness):
    """Calcule le chemin de randonnée en mode crossing ou en mode boucle"""
    if is_loop:
        return best_hiking_loop(
            start_coord=departure_stop_info["node"],
            max_distance_m=max_distance_m,
            G=G, poi_data=poi_data,
            randomness=randomness, massif_name=massif_clean,
        )
    return best_hiking_crossing(
        start_coord=departure_stop_info["node"],
        end_coord=candidate["stop_info"]["node"],
        max_distance_m=max_distance_m,
        G=G, poi_data=poi_data, randomness=randomness,
    )


def _try_candidates(candidates, departure_stop_id, departure_stop_info, massif, massif_clean,
                    max_distance_m, G, poi_data, randomness, travel_go,
                    departure_time, return_time, level, stops_data, address, status_callback):
    """Teste les candidats d'arrêt de retour en calculant le trajet de retour TC puis le chemin de randonnée associé."""
    for candidate in candidates:
        update_status("Test d'arrêts pour le trajet retour", status_callback, 40)
        try:
            _, travel_return, duration = compute_return_transit(
                [candidate], return_time, address,
                stops_data=stops_data, departure_time=departure_time,
                status_callback=status_callback,
            )
        except Exception as e:
            logger.warning(f"Pas de retour TC pour {candidate.get('stop_id')}: {e}")
            continue

        adjusted_max, _ = initialize_route_parameters(
            massif_name=massif, departure_time=departure_time, return_time=return_time,
            level=level, transit_route=travel_go, return_transit_seconds=duration,
        )
        logger.info(f"Distance max ajustée : {adjusted_max/1000:.1f} km")

        update_status("Calcul du chemin de randonnée", status_callback, 55)
        try:
            path, dist = _compute_hike(
                candidate, _is_loop(candidate, departure_stop_id, departure_stop_info),
                departure_stop_info, massif_clean, adjusted_max, G, poi_data, randomness,
            )
        except Exception as e:
            logger.warning(f"Échec chemin pour {candidate.get('stop_id')}: {e}")
            continue

        return candidate, travel_return, path, dist

    return None, None, None, None


def _fallback(candidates, departure_stop_info, max_distance_m, G, poi_data, randomness):
    if not candidates:
        return [], 0
    try:
        path, dist = best_hiking_crossing(
            start_coord=departure_stop_info["node"],
            end_coord=candidates[0]["stop_info"]["node"],
            max_distance_m=max_distance_m,
            G=G, poi_data=poi_data, randomness=randomness,
        )
        logger.warning(f"Trajet de repli calculé vers {candidates[0].get('stop_id')}")
        return path, dist
    except Exception as e:
        logger.warning(f"Échec trajet de repli : {e}")
        return [], 0


def compute_crossing_route(departure_stop_info, departure_stop_id, massif, massif_clean,
                            max_distance_m, G, poi_data, stops_data, randomness,
                            travel_go, departure_time, return_time, level,
                            transit_priority, address, status_callback):
    update_status("Recherche des arrêts retour", status_callback, 35)
    return_error_message = None

    try:
        return_candidates = choose_return_stop(
            departure_stop_info=departure_stop_info,
            stops_data=stops_data,
            distance_max_m=max_distance_m,
            transit_priority=transit_priority,
        )
        logger.info(f"{len(return_candidates)} candidats retour trouvés")
    except Exception as e:
        return_candidates = []
        return_error_message = f"Aucun arrêt retour plausible trouvé : {e}"
        logger.warning(f"{return_error_message}")

    candidate, travel_return, path, dist = _try_candidates(
        return_candidates, departure_stop_id, departure_stop_info,
        massif, massif_clean, max_distance_m, G, poi_data, randomness,
        travel_go, departure_time, return_time, level, stops_data, address, status_callback,
    )

    if candidate is None:
        return_error_message = return_error_message or "Aucun itinéraire retour TC valide trouvé"
        logger.warning(f"{return_error_message}")
        path, dist = _fallback(return_candidates, departure_stop_info, max_distance_m, G, poi_data, randomness)
        travel_return = None

    return {
        "path": path or [],
        "dist": dist or 0,
        "travel_return": travel_return,
        "return_error_message": return_error_message,
    }
