"""
Algorithmes de traversée (départ → arrivée) et de boucle (départ = arrivée).
"""
import logging

from networkx import NetworkXNoPath, shortest_path

logger = logging.getLogger(__name__)

from ..utils.geotools import (
    find_nearest_node,
    save_original_weights, restore_original_weights,
    get_path_length, get_path_coordinates, penalize_path_edges,
)
from ..utils.poi_tools import (
    get_massif_center, filter_poi_by_path_distance, compute_midpoint,
    collect_buffer_pois, build_optimal_poi_path,
)


def _direct_path_fallback(start_coord, end_coord, G):
    """Chemin direct le plus court entre départ et arrivée."""
    start_node = find_nearest_node(G, start_coord[::-1])
    end_node = find_nearest_node(G, end_coord[::-1])
    try:
        path = shortest_path(G, start_node, end_node, weight="length")
        length = get_path_length(G, path)
        logger.info(f"Trajet direct : {length/1000:.1f} km")
        return path, length
    except NetworkXNoPath:
        return [], 0


def best_hiking_crossing(start_coord, end_coord, max_distance_m, G, poi_data, randomness=0.3):
    """Traversée optimisant la distance et les POI le long d'un axe départ → arrivée."""
    logger.info(f"Recherche traversée : {start_coord} → {end_coord}, max {max_distance_m/1000:.1f} km")

    all_pois = collect_buffer_pois(poi_data, start_coord, end_coord, max_distance_m, randomness)
    if not all_pois:
        return _direct_path_fallback(start_coord, end_coord, G)

    selected_pois, final_path = build_optimal_poi_path(
        start_coord, end_coord, all_pois, max_distance_m, G
    )

    if not selected_pois:
        start_node = find_nearest_node(G, start_coord[::-1])
        poi_node = find_nearest_node(G, all_pois[0]["coord"][::-1])
        end_node = find_nearest_node(G, end_coord[::-1])
        try:
            path_to_poi = shortest_path(G, start_node, poi_node, weight="length")
            path_from_poi = shortest_path(G, poi_node, end_node, weight="length")
            final_path = path_to_poi + path_from_poi[1:]
            selected_pois = [all_pois[0]]
        except Exception:
            return _direct_path_fallback(start_coord, end_coord, G)

    try:
        length = get_path_length(G, final_path)
        logger.info(f"Traversée : {length/1000:.1f} km, {len(selected_pois)} POI")
        return final_path, length
    except Exception:
        return _direct_path_fallback(start_coord, end_coord, G)


def best_hiking_loop(start_coord, max_distance_m, G, poi_data, randomness=0.3, massif_name="Chartreuse"):
    """Boucle : aller vers un point intermédiaire (40%), retour par un tracé différent (60%)."""
    logger.info(f"Boucle : départ={start_coord}, max {max_distance_m/1000:.1f} km")

    massif_center = get_massif_center(massif_name)
    midpoint = compute_midpoint(start_coord, massif_center, max_distance_m, poi_data)

    original_weights = save_original_weights(G)

    path_go, dist_go = best_hiking_crossing(
        start_coord=start_coord,
        end_coord=midpoint,
        max_distance_m=max_distance_m * 0.4,
        G=G,
        poi_data=poi_data,
        randomness=randomness,
    )

    if not path_go:
        logger.warning("Aucun chemin aller pour la boucle")
        return [], 0

    go_coords = get_path_coordinates(G, path_go)
    penalize_path_edges(G, path_go, original_weights)

    filtered_pois = filter_poi_by_path_distance(poi_data, go_coords, max_distance_m=200)
    logger.info(f"POI disponibles pour le retour : {len(filtered_pois.get('features', []))}")

    path_return, dist_return = best_hiking_crossing(
        start_coord=midpoint,
        end_coord=start_coord,
        max_distance_m=max_distance_m * 0.6,
        G=G,
        poi_data=filtered_pois,
        randomness=randomness,
    )

    restore_original_weights(G, original_weights)

    if not path_return:
        logger.warning("Aucun chemin retour pour la boucle")
        return [], 0

    complete_path = path_go + path_return[1:]
    total = dist_go + dist_return
    logger.info(f"Boucle : aller {dist_go/1000:.1f} km + retour {dist_return/1000:.1f} km = {total/1000:.1f} km")
    return complete_path, total
