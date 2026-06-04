"""
Algorithme de tour de massif : progression sectorielle autour du centre du massif.
"""
import logging

from networkx import NetworkXNoPath, shortest_path

logger = logging.getLogger(__name__)

from ..utils.geotools import find_nearest_node, save_original_weights, restore_original_weights, get_path_length, determine_rotation_direction
from ..utils.poi_tools import get_massif_center, find_poi_candidates, select_best_poi
from hello.constants import REUSE_PENALTY_MULTIPLIER


def _run_tour_loop(G, start_coord, poi_data, massif_center, rotation_dir,
                   max_distance_m, randomness, original_weights):
    """Boucle principale du tour : sélection successive de POI dans la direction de rotation."""
    current_coord = start_coord
    current_node = find_nearest_node(G, start_coord[::-1])
    remaining = max_distance_m
    path_nodes = [current_node]
    path_coords = [start_coord]
    visited_pois = set()
    used_edges = {}

    while remaining > 10000:
        candidates = find_poi_candidates(
            current_coord, poi_data, 5000, visited_pois, path_coords,
            path_exclusion_m=2000, massif_center=massif_center, rotation_direction=rotation_dir,
        )
        if not candidates:
            candidates = find_poi_candidates(
                current_coord, poi_data, 30000, visited_pois, path_coords,
                path_exclusion_m=2000, massif_center=massif_center, rotation_direction=rotation_dir,
            )
        if not candidates:
            candidates = find_poi_candidates(current_coord, poi_data, 30000, visited_pois, path_coords)
        if not candidates:
            logger.info(f"Aucun POI, arrêt (restant : {remaining/1000:.1f} km)")
            break

        best = select_best_poi(candidates, randomness)
        poi_node = find_nearest_node(G, best["coord"][::-1])

        segment = shortest_path(G, current_node, poi_node, weight="length")
        seg_len = get_path_length(G, segment)
        if seg_len > remaining:
            logger.info(f"POI trop loin ({seg_len/1000:.1f} km > {remaining/1000:.1f} km restants)")
            break

        for i in range(len(segment) - 1):
            u, v = segment[i], segment[i + 1]
            key = (u, v) if (u, v) in original_weights else (v, u)
            count = used_edges.get(key, 0)
            used_edges[key] = count + 1
            new_w = original_weights[key] * (1 + REUSE_PENALTY_MULTIPLIER * (count + 1))
            if G.has_edge(u, v): G[u][v]["length"] = new_w
            if G.has_edge(v, u): G[v][u]["length"] = new_w

        path_nodes.extend(segment[1:])
        for node in segment[1:]:
            if node in G.nodes and "lon" in G.nodes[node]:
                path_coords.append((G.nodes[node]["lon"], G.nodes[node]["lat"]))

        current_node = poi_node
        current_coord = best["coord"]
        remaining -= seg_len
        visited_pois.add(best["id"])
        logger.info(f"POI '{best['id']}' ajouté, restant : {remaining/1000:.1f} km")

    return path_nodes


def best_hiking_massif_tour(start_coord, max_distance_m, G, poi_data, stops_data,
                             randomness=0.3, massif_name="Chartreuse"):
    """Tour progressif du massif en suivant les POI dans le sens de rotation choisi."""
    logger.info(f"Tour massif : départ={start_coord}, max {max_distance_m/1000:.1f} km")

    massif_center = get_massif_center(massif_name)
    rotation_dir = determine_rotation_direction()
    logger.info(f"Sens : {'horaire' if rotation_dir == 'clockwise' else 'anti-horaire'}")

    original_weights = save_original_weights(G)
    try:
        path_nodes = _run_tour_loop(
            G, start_coord, poi_data, massif_center,
            rotation_dir, max_distance_m, randomness, original_weights
        )
    except NetworkXNoPath:
        restore_original_weights(G, original_weights)
        return [], 0

    restore_original_weights(G, original_weights)
    total_distance = get_path_length(G, path_nodes)
    logger.info(f"Tour terminé : {total_distance/1000:.1f} km")
    return path_nodes, total_distance
