"""
Tracé de randonnée construit point par point : arrêt de départ → POI choisis,
dans l'ordre des clics de l'utilisateur → arrêt retour (une fois le tracé terminé).

Chaque tronçon est le plus court chemin dans le graphe, en pénalisant les arêtes
déjà empruntées (même règle que le mode POI automatique, cf. route_poi._chain_pois).
On utilise A* plutôt que Dijkstra : même résultat, 2 à 4 fois plus rapide ici,
l'heuristique (distance à vol d'oiseau) ne surestimant jamais une longueur d'arête.

Les préfixes déjà calculés sont mémorisés : ajouter un point ne calcule que le
nouveau tronçon.
"""

import json
import logging
import os
from collections import OrderedDict

from django.conf import settings
from networkx import astar_path, NetworkXNoPath, NodeNotFound

from hello.constants import REUSE_PENALTY_MULTIPLIER
from hello.data_preparation.utils import slugify
from hello.routing.domain.elevation import get_elevations, smooth_elevations, compute_total_ascent
from hello.routing.utils.geotools import haversine, get_path_length
from .graph_cache import get_massif_graph
from .stops import load_stops

logger = logging.getLogger(__name__)

PREFIX_CACHE_SIZE = 64


class UnreachablePoint(Exception):
    """Le point demandé n'est pas relié au tracé par le réseau de sentiers."""


def load_poi_geojson(massif):
    path = os.path.join(settings.BASE_DIR, "data", "output", f"{slugify(massif)}_poi_scores.geojson")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_pois(massif):
    """POI du massif ; leur identifiant est leur position dans le fichier."""
    features = load_poi_geojson(massif).get("features", [])

    pois = []
    for index, feature in enumerate(features):
        props = feature.get("properties", {})
        lon, lat = feature["geometry"]["coordinates"][:2]
        pois.append({
            "id": index,
            "titre": props.get("titre") or "Point d'intérêt",
            "type": props.get("type"),
            "elevation": props.get("elevation"),
            "lon": lon,
            "lat": lat,
        })
    return pois


def _node_distance(u, v):
    """Distance à vol d'oiseau entre deux nœuds (lon, lat) : heuristique A*."""
    return haversine((u[1], u[0]), (v[1], v[0]))


# (slug, stop_id, (clé de cible, ...)) -> {"nodes": [...], "traversed": set d'arêtes}
# Une cible est un POI (clé : son identifiant) ou l'arrêt retour (clé : "stop:<id>").
_prefix_cache = OrderedDict()


def _remember(key, value):
    _prefix_cache[key] = value
    _prefix_cache.move_to_end(key)
    while len(_prefix_cache) > PREFIX_CACHE_SIZE:
        _prefix_cache.popitem(last=False)


def _chain(massif_graph, slug, stop_id, start_node, target_nodes, target_keys):
    """Chemin nœud à nœud départ → cibles, construit récursivement sur les préfixes."""
    key = (slug, stop_id, tuple(target_keys))
    if key in _prefix_cache:
        _prefix_cache.move_to_end(key)
        return _prefix_cache[key]

    if not target_keys:
        result = {"nodes": [start_node], "traversed": set()}
        _remember(key, result)
        return result

    previous = _chain(massif_graph, slug, stop_id, start_node, target_nodes[:-1], target_keys[:-1])
    traversed = previous["traversed"]

    def penalized_weight(u, v, data):
        base = data.get("length", 1)
        return base * REUSE_PENALTY_MULTIPLIER if (u, v) in traversed else base

    source, target = previous["nodes"][-1], target_nodes[-1]
    try:
        segment = astar_path(
            massif_graph.G, source, target,
            heuristic=_node_distance, weight=penalized_weight,
        )
    except (NetworkXNoPath, NodeNotFound):
        raise UnreachablePoint(
            "Ce point n'est pas relié au tracé par le réseau de sentiers."
        )

    new_traversed = set(traversed)
    for u, v in zip(segment, segment[1:]):
        new_traversed.add((u, v))
        new_traversed.add((v, u))

    result = {"nodes": previous["nodes"] + segment[1:], "traversed": new_traversed}
    _remember(key, result)
    return result


def compute_hike(massif, stop_id, poi_ids, end_stop_id=None):
    """
    Tracé arrêt `stop_id` → POI `poi_ids` (dans cet ordre) → arrêt `end_stop_id`
    s'il est fourni.

    Retourne {"coordinates": [[lon, lat, ele], ...], "distance_m", "ascent_m",
              "elevation_failed", "end": [lon, lat]}.
    """
    slug = slugify(massif)
    stops = load_stops(massif)
    stop_info = stops.get(str(stop_id))
    if stop_info is None:
        raise ValueError(f"Arrêt inconnu : {stop_id}")
    end_stop_info = None
    if end_stop_id not in (None, ""):
        end_stop_info = stops.get(str(end_stop_id))
        if end_stop_info is None:
            raise ValueError(f"Arrêt inconnu : {end_stop_id}")

    pois = load_pois(massif)
    try:
        selected = [pois[int(i)] for i in poi_ids]
    except (IndexError, ValueError, TypeError):
        raise ValueError("Point d'intérêt inconnu")

    massif_graph = get_massif_graph(massif)
    start_node = massif_graph.nearest_node(stop_info["node"][0], stop_info["node"][1])
    target_nodes = [massif_graph.nearest_node(p["lon"], p["lat"]) for p in selected]
    target_keys = [p["id"] for p in selected]
    if end_stop_info is not None:
        target_nodes.append(massif_graph.nearest_node(end_stop_info["node"][0], end_stop_info["node"][1]))
        target_keys.append(f"stop:{end_stop_id}")

    chain = _chain(massif_graph, slug, str(stop_id), start_node, target_nodes, target_keys)
    nodes = chain["nodes"]
    G = massif_graph.G

    path = [(lon, lat) for lon, lat in nodes]
    elevations = get_elevations(path, G)
    elevation_failed = all(e == 0 for e in elevations)
    smoothed = smooth_elevations(elevations, path)

    return {
        "coordinates": [[lon, lat, round(ele)] for (lon, lat), ele in zip(path, smoothed)],
        "distance_m": round(get_path_length(G, nodes)),
        "ascent_m": compute_total_ascent(smoothed),
        "elevation_failed": elevation_failed,
        "end": list(nodes[-1]),
    }
