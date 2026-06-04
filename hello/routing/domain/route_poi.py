"""
Mode POI : itinéraire contraint par des points d'intérêt choisis par l'utilisateur.
"""
import logging

from networkx import shortest_path

logger = logging.getLogger(__name__)

from ..utils.geotools import find_nearest_node, haversine, get_path_coordinates, get_path_length
from .transit_go import get_best_transit_route
from .transit_back import choose_return_stop, compute_return_transit
from .route_init import initialize_route_parameters
from ..utils.poi_tools import resolve_pois, sort_pois_polar
from .progress import update_status
from hello.constants import REUSE_PENALTY_MULTIPLIER


def _chain_pois(G, pois):
    """Construit le chemin nœud à nœud entre les POI avec pénalisation des arêtes réutilisées."""
    traversed_edges = set()

    def penalized_weight(u, v, data):
        base = data.get("length", 1)
        return base * REUSE_PENALTY_MULTIPLIER if (u, v) in traversed_edges else base

    path_nodes = [pois[0]["node"]]
    for poi in pois[1:]:
        try:
            segment = shortest_path(G, path_nodes[-1], poi["node"], weight=penalized_weight)
            for j in range(len(segment) - 1):
                traversed_edges.add((segment[j], segment[j + 1]))
                traversed_edges.add((segment[j + 1], segment[j]))
            path_nodes.extend(segment[1:])
        except Exception as e:
            logger.warning(f"Chemin impossible vers POI {poi['id']}: {e}")

    return path_nodes, traversed_edges, penalized_weight



def _find_transit_go(pois, stops_data, search_radius, randomness, departure_time,
                     return_time, address, transit_priority, hubs_entree_data, status_callback):
    """Trouve le transport aller vers le premier POI."""
    update_status("Calcul du transport aller", status_callback, 45)
    first_poi = pois[0]
    first_poi_latlon = (first_poi["coord"][1], first_poi["coord"][0])

    nearby_stops = {
        sid: info for sid, info in stops_data.items()
        if haversine(first_poi_latlon, (info["node"][1], info["node"][0])) <= search_radius
    }
    if not nearby_stops:
        raise RuntimeError(f"Aucun arrêt de transport trouvé autour du POI {first_poi['id']}")

    travel_go, departure_stop_id, departure_stop_info = get_best_transit_route(
        randomness=randomness, departure_time=departure_time, return_time=return_time,
        stops_data=nearby_stops, address=address, transit_priority=transit_priority,
        hubs_entree_data=hubs_entree_data,
    )
    return travel_go, departure_stop_id, departure_stop_info


def _extract_transit_arrival(travel_go, departure_stop_info):
    """Extrait le point d'arrivée TC depuis l'itinéraire aller."""
    try:
        steps = travel_go["routes"][0]["legs"][0]["steps"]
        transit_steps = [s for s in steps if s.get("travelMode") == "TRANSIT"]
        if transit_steps:
            last = transit_steps[-1]
            lat = last.get("endLocation", {}).get("latLng", {}).get("latitude")
            lon = last.get("endLocation", {}).get("latLng", {}).get("longitude")
            if lat and lon:
                return lat, lon
    except Exception:
        pass
    return departure_stop_info["node"][1], departure_stop_info["node"][0]


def _find_transit_return(pois, stops_data, search_radius, return_time, address,
                         departure_time, transit_priority, status_callback):
    """Trouve le transport retour depuis le dernier POI."""
    update_status("Calcul du transport retour", status_callback, 55)
    last_poi = pois[-1]
    last_poi_stop_info = {"node": last_poi["node"], "properties": {}}

    return_candidates = choose_return_stop(
        departure_stop_info=last_poi_stop_info,
        stops_data=stops_data,
        distance_max_m=max(search_radius, 10000),
        transit_priority=transit_priority,
    )
    for candidate in return_candidates:
        try:
            best_candidate, travel_return, _ = compute_return_transit(
                [candidate], return_time, address,
                stops_data=stops_data, departure_time=departure_time,
                status_callback=status_callback,
            )
            return best_candidate, travel_return
        except Exception:
            pass
    raise RuntimeError("Aucun itinéraire de transport en commun retour trouvé")


def _build_final_path(G, transit_arrival_lat, transit_arrival_lon, pois,
                      poi_coords, return_stop_info, traversed_edges, penalized_weight):
    """Assemble : walk TC→POI1 + chemin POI + walk POIlast→TC retour."""
    def node_coords(n):
        lon = G.nodes[n].get("lon") or (n[0] if isinstance(n, tuple) else None)
        lat = G.nodes[n].get("lat") or (n[1] if isinstance(n, tuple) else None)
        return lon, lat

    final_path = []

    departure_node = find_nearest_node(G, (transit_arrival_lat, transit_arrival_lon))
    try:
        walk_to_first = shortest_path(G, departure_node, pois[0]["node"], weight=penalized_weight)
        for j in range(len(walk_to_first) - 1):
            traversed_edges.add((walk_to_first[j], walk_to_first[j + 1]))
        for n in walk_to_first[:-1]:
            lon, lat = node_coords(n)
            if lon is not None:
                final_path.append((lon, lat))
    except Exception as e:
        logger.warning(f"Walk TC→POI1 impossible : {e}")

    final_path.extend(poi_coords)

    return_node = find_nearest_node(G, (return_stop_info["node"][1], return_stop_info["node"][0]))
    try:
        walk_from_last = shortest_path(G, pois[-1]["node"], return_node, weight=penalized_weight)
        for n in walk_from_last[1:]:
            lon, lat = node_coords(n)
            if lon is not None:
                final_path.append((lon, lat))
    except Exception as e:
        logger.warning(f"Walk POIlast→TC retour impossible : {e}")

    final_path.append((return_stop_info["node"][0], return_stop_info["node"][1]))
    return final_path


def compute_poi_route(randomness, massif, departure_time, return_time, level, address,
                      transit_priority, pois, stops_data, G, poi_data,
                      hubs_entree_data, status_callback=None):
    selected_pois = resolve_pois(poi_data, pois, G)
    selected_pois = sort_pois_polar(selected_pois, massif)
    update_status("POI ordonnés géographiquement", status_callback, 15)

    path_nodes, traversed_edges, penalized_weight = _chain_pois(G, selected_pois)
    poi_coords = get_path_coordinates(G, path_nodes)
    poi_distance = get_path_length(G, path_nodes)
    update_status("Chemin construit entre les points sélectionnés", status_callback, 25)

    max_distance_m, route_type = initialize_route_parameters(
        massif_name=massif, departure_time=departure_time, return_time=return_time,
        level=level, transit_route=None, return_transit_seconds=None,
    )
    search_radius = max(max_distance_m - poi_distance, 10000)
    logger.info(f"Distance max : {max_distance_m/1000:.1f} km | distance POI : {poi_distance/1000:.1f} km")

    travel_go, _, departure_stop_info = _find_transit_go(
        selected_pois, stops_data, search_radius, randomness,
        departure_time, return_time, address, transit_priority, hubs_entree_data, status_callback,
    )
    transit_arrival_lat, transit_arrival_lon = _extract_transit_arrival(travel_go, departure_stop_info)

    return_candidate, travel_return = _find_transit_return(
        selected_pois, stops_data, search_radius, return_time,
        address, departure_time, transit_priority, status_callback,
    )

    update_status("Construction du chemin final", status_callback, 60)
    final_path = _build_final_path(
        G, transit_arrival_lat, transit_arrival_lon, selected_pois,
        poi_coords, return_candidate["stop_info"], traversed_edges, penalized_weight,
    )

    update_status("Chemin avec POI calculé", status_callback, 65)
    return {
        "path": final_path,
        "dist": poi_distance,
        "travel_go": travel_go,
        "travel_return": travel_return,
        "route_type": route_type,
        "return_error_message": None,
    }
