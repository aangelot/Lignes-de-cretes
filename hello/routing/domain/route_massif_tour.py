"""
Mode massif_tour : boucle autour du massif, arrêt retour trouvé depuis le point d'arrivée.
"""
import logging

from networkx import NetworkXNoPath, shortest_path

logger = logging.getLogger(__name__)
from ..utils.geotools import find_nearest_node
from .transit_back import choose_return_stop, compute_return_transit
from .hiking_massif_tour import best_hiking_massif_tour
from .progress import update_status


def _find_return_candidates(arrival_stop_info, stops_data, transit_priority):
    """Cherche des arrêts retour en élargissant le rayon si nécessaire (20 → 50 km)."""
    for radius in (20000, 50000):
        try:
            candidates = choose_return_stop(
                departure_stop_info=arrival_stop_info,
                stops_data=stops_data,
                distance_max_m=radius,
                transit_priority=transit_priority,
            )
            if candidates:
                logger.info(f"{len(candidates)} candidats retour trouvés dans {radius/1000:.0f} km")
                return candidates
        except Exception as e:
            logger.warning(f"Erreur recherche retour {radius/1000:.0f}km : {e}")
    return []


def _extend_to_stop(G, hike_path, hike_distance, final_coord, selected_candidate):
    """Étend le chemin de rando jusqu'à l'arrêt TC retour."""
    stop_id = selected_candidate.get("stop_id")
    try:
        start_node = find_nearest_node(G, final_coord[::-1])
        end_node = find_nearest_node(G, selected_candidate["stop_info"]["node"][::-1])
        path_to_stop = shortest_path(G, start_node, end_node, weight="length")
        distance_to_stop = sum(
            G[path_to_stop[i]][path_to_stop[i + 1]]["length"]
            for i in range(len(path_to_stop) - 1)
        )
        logger.info(f"Distance vers arrêt TC : {distance_to_stop/1000:.1f} km")
        hike_path.extend(path_to_stop[1:])
        return hike_path, hike_distance + distance_to_stop, None
    except NetworkXNoPath:
        return hike_path, hike_distance, f"Aucun chemin piéton vers l'arrêt TC {stop_id}"
    except Exception as e:
        return hike_path, hike_distance, f"Erreur calcul trajet vers arrêt TC : {e}"


def compute_massif_tour_route(departure_stop_info, max_distance_m, massif_clean, G, poi_data,
                               stops_data, randomness, departure_time, return_time,
                               address, transit_priority, status_callback):
    update_status("Mode tour du massif choisi", status_callback, 45)

    hike_path, hike_distance = best_hiking_massif_tour(
        start_coord=departure_stop_info["node"],
        max_distance_m=max_distance_m,
        G=G, poi_data=poi_data, stops_data=stops_data,
        randomness=randomness, massif_name=massif_clean,
    )
    if not hike_path:
        raise RuntimeError("Aucun chemin de randonnée trouvé pour massif_tour")

    logger.info(f"Distance randonnée tour : {hike_distance/1000:.1f} km")
    final_coord = hike_path[-1]
    arrival_stop_info = {"node": final_coord, "properties": {}}

    update_status("Recherche des arrêts retour depuis l'arrivée", status_callback, 60)
    return_candidates = _find_return_candidates(arrival_stop_info, stops_data, transit_priority)

    selected_candidate = travel_return = return_error_message = None

    if return_candidates:
        try:
            selected_candidate, travel_return, _ = compute_return_transit(
                return_candidates, return_time, address,
                stops_data=stops_data, departure_time=departure_time,
                status_callback=status_callback,
            )
        except Exception:
            return_error_message = "Aucun arrêt retour valide trouvé après élargissement à 50km"
            logger.warning(f"{return_error_message}")

    if selected_candidate:
        hike_path, hike_distance, walk_error = _extend_to_stop(
            G, hike_path, hike_distance, final_coord, selected_candidate
        )
        if walk_error:
            return_error_message = walk_error
            logger.warning(f"{walk_error}")
    else:
        return_error_message = return_error_message or "Aucun arrêt retour valide trouvé"

    return {
        "path": hike_path,
        "dist": hike_distance,
        "travel_return": travel_return,
        "return_error_message": return_error_message,
    }
