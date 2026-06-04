"""
Utilitaires POI : filtrage, recherche de proximité, extraction near path.
"""
import logging
import math
import json
import os
import random

logger = logging.getLogger(__name__)

from shapely.geometry import LineString, Point
from networkx import NetworkXNoPath, shortest_path
from django.conf import settings
from hello.data_preparation.utils import slugify
from hello.constants import REUSE_PENALTY_MULTIPLIER
from .geotools import haversine, find_nearest_node, save_original_weights, restore_original_weights, get_path_length, angle_in_sector


def get_massif_center(massif_name="Chartreuse"):
    """Lit le centre du massif depuis le GeoJSON de référence."""
    geojson_path = "data/input/massifs_coord_max_with_centers.geojson"
    massif_slug = slugify(massif_name)
    try:
        with open(geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            if slugify(props.get("nom_pnr", "")) == massif_slug:
                centre = props.get("centre")
                if centre:
                    return (centre["longitude"], centre["latitude"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Erreur lecture massif '{massif_name}': {e}")
    return (5.79889015, 45.3798141)  # Chartreuse par défaut

def get_massif_diagonal_km(massif_name):
    """Lit la diagonale du massif depuis massifs_coord_max.geojson."""
    file_path = os.path.join(settings.BASE_DIR, "data", "input", "massifs_coord_max.geojson")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    massif_name = slugify(massif_name)
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if slugify(props.get("nom_pnr", "")) == massif_name:
            return float(props.get("diagonal_km"))
    raise RuntimeError(f"Diagonale introuvable pour le massif '{massif_name}'")

def compute_midpoint(start_coord, massif_center, max_distance_m, poi_data):
    """
    Projette un point intermédiaire au tiers de la distance max vers le centre du massif,
    puis le snape sur le POI le plus proche.
    """
    start_lon, start_lat = start_coord
    center_lon, center_lat = massif_center
    angle = math.atan2(center_lat - start_lat, center_lon - start_lon)
    target_dist_deg = (max_distance_m / 3) / 111000
    mid = (
        start_lon + target_dist_deg * math.cos(angle),
        start_lat + target_dist_deg * math.sin(angle),
    )
    nearest_coord, nearest_titre, nearest_dist = _find_nearest_poi(mid, poi_data)
    if nearest_coord:
        logger.info(f"Point intermédiaire : POI '{nearest_titre}' à {nearest_dist:.0f} m du fictif")
        return nearest_coord
    logger.info(f"Point intermédiaire fictif à {haversine(start_coord, mid):.0f} m du départ")
    return mid


def _is_poi_close_to_path(poi_coord, path_coords, max_distance_m=1000):
    """Retourne True si le POI est à moins de max_distance_m du chemin."""
    return any(haversine(poi_coord, pt) < max_distance_m for pt in path_coords)


def _find_nearest_poi(coord, poi_data, max_search_radius_m=None):
    """Retourne (coord, titre, dist) du POI le plus proche. None si hors rayon."""
    best_dist = float("inf")
    best_coord = best_titre = None
    for feat in poi_data.get("features", []):
        coords = feat.get("geometry", {}).get("coordinates")
        if not coords or len(coords) < 2:
            continue
        poi_coord = tuple(coords)
        dist = haversine(coord, poi_coord)
        if dist < best_dist:
            best_dist, best_coord = dist, poi_coord
            best_titre = feat.get("properties", {}).get("titre")
    if max_search_radius_m and best_dist > max_search_radius_m:
        return None, None, best_dist
    return best_coord, best_titre, best_dist


def filter_poi_by_path_distance(poi_data, path_coords, excluded_poi_ids=None, max_distance_m=200):
    """Filtre les POI trop proches du chemin ou dans la liste d'exclusion."""
    excluded_ids = excluded_poi_ids or set()
    filtered_features = []
    for feat in poi_data.get("features", []):
        poi_id = feat.get("properties", {}).get("titre")
        if poi_id in excluded_ids:
            continue
        coords = feat.get("geometry", {}).get("coordinates")
        if not coords or len(coords) < 2:
            filtered_features.append(feat)
            continue
        if not _is_poi_close_to_path(tuple(coords), path_coords, max_distance_m):
            filtered_features.append(feat)
    logger.info(f"Filtrage POI: {len(poi_data.get('features', []))} → {len(filtered_features)}")
    return {"type": poi_data.get("type", "FeatureCollection"), "features": filtered_features}


def collect_buffer_pois(poi_data, start_coord, end_coord, max_distance_m, randomness):
    """Collecte les POI dans le buffer autour de la ligne directe, 5 premiers triés par score."""
    direct_line = LineString([start_coord, end_coord])
    buffer_km = 10 if max_distance_m >= 20000 else 2
    buffer_geom = direct_line.buffer(buffer_km / 111.0, cap_style=2)

    pois = []
    for feat in poi_data.get("features", []):
        if buffer_geom.contains(Point(feat["geometry"]["coordinates"])):
            base_score = float(feat["properties"].get("score", 0.0))
            pois.append({
                "id": feat["properties"].get("titre"),
                "coord": tuple(feat["geometry"]["coordinates"]),
                "score": (1 - randomness) * base_score + randomness * random.uniform(0, 1),
                "properties": feat["properties"],
                "projection": direct_line.project(Point(feat["geometry"]["coordinates"])),
            })
    pois.sort(key=lambda x: x["score"], reverse=True)
    return pois[:5]


def _greedy_poi_selection(G, start_node, pois_by_projection, max_distance_m, original_weights):
    """Sélection gloutonne des POI dans l'ordre de projection, avec pénalité de réutilisation."""
    used_edges = {}
    partial_path = [start_node]
    current_node = start_node
    remaining = max_distance_m
    selected = []

    for poi in pois_by_projection:
        poi_node = find_nearest_node(G, poi["coord"][::-1])
        try:
            segment = shortest_path(G, current_node, poi_node, weight="length")
            seg_len = get_path_length(G, segment)
            if seg_len > remaining:
                continue
            selected.append(poi)
            for i in range(len(segment) - 1):
                u, v = segment[i], segment[i + 1]
                key = (u, v) if (u, v) in original_weights else (v, u)
                count = used_edges.get(key, 0)
                used_edges[key] = count + 1
                new_w = original_weights[key] * (1 + REUSE_PENALTY_MULTIPLIER * (count + 1))
                if G.has_edge(u, v): G[u][v]["length"] = new_w
                if G.has_edge(v, u): G[v][u]["length"] = new_w
            partial_path.extend(segment[1:])
            current_node = poi_node
            remaining -= seg_len
        except NetworkXNoPath:
            continue

    return selected, partial_path, current_node, remaining


def _finalize_path_to_end(G, selected, partial_path, start_node, end_node, remaining):
    """Valide et construit le chemin final jusqu'à l'arrivée."""
    if not selected:
        return [], []
    try:
        final_seg = shortest_path(G, partial_path[-1], end_node, weight="length")
        if get_path_length(G, final_seg) <= remaining:
            return selected, partial_path + final_seg[1:]

        if len(selected) > 1:
            removed = selected.pop()
            logger.warning(f"POI '{removed['id']}' retiré pour atteindre l'arrivée")
            partial_path = [start_node]
            for p in selected:
                poi_node = find_nearest_node(G, p["coord"][::-1])
                seg = shortest_path(G, partial_path[-1], poi_node, weight="length")
                partial_path.extend(seg[1:])
            final_seg = shortest_path(G, partial_path[-1], end_node, weight="length")
            return selected, partial_path + final_seg[1:]
        return [], []
    except NetworkXNoPath:
        if selected:
            logger.warning(f"POI '{selected[-1]['id']}' retiré (arrivée inaccessible)")
        return [], []


def build_optimal_poi_path(start_coord, end_coord, all_pois, max_distance_m, G):
    """Sélectionne la séquence optimale de POI et construit le chemin complet."""
    start_node = find_nearest_node(G, start_coord[::-1])
    end_node = find_nearest_node(G, end_coord[::-1])

    try:
        shortest_path(G, start_node, end_node, weight="length")
    except NetworkXNoPath:
        return [], []

    original_weights = save_original_weights(G)
    pois_by_projection = sorted(all_pois, key=lambda x: x["projection"])

    selected, partial_path, _, remaining = _greedy_poi_selection(
        G, start_node, pois_by_projection, max_distance_m, original_weights
    )
    selected, final_path = _finalize_path_to_end(
        G, selected, partial_path, start_node, end_node, remaining
    )
    restore_original_weights(G, original_weights)
    return selected, final_path


def resolve_pois(poi_data, requested_pois, G):
    """Résout les POI demandés en coordonnées + nœuds de graphe."""
    selected = []
    for feat in poi_data.get("features", []):
        title = feat["properties"].get("titre")
        if title in requested_pois:
            lon, lat = feat["geometry"]["coordinates"]
            selected.append({
                "id": title,
                "coord": (lon, lat),
                "node": find_nearest_node(G, (lat, lon)),
                "properties": feat.get("properties", {}),
            })
    if not selected:
        raise RuntimeError("Aucun POI valide trouvé")
    return selected


def sort_pois_polar(pois, massif):
    """Trie les POI par angle polaire autour du centre du massif, direction aléatoire."""
    center_lon, center_lat = get_massif_center(massif)
    pois.sort(key=lambda p: math.atan2(p["coord"][1] - center_lat, p["coord"][0] - center_lon))
    if random.random() < 0.5:
        pois = list(reversed(pois))
    return pois


def find_poi_candidates(current_coord, poi_data, max_distance, visited_pois, path_coords,
                         path_exclusion_m=1000, massif_center=None, rotation_direction=None):
    """
    Trouve les POI candidats dans un rayon autour de current_coord.
    Si massif_center et rotation_direction sont fournis, applique un filtre sectoriel de 135°.
    """
    sector_filter = massif_center is not None and rotation_direction is not None
    if sector_filter:
        mcx, mcy = massif_center
        current_angle = math.atan2(current_coord[1] - mcy, current_coord[0] - mcx)
        sector = 3 * math.pi / 4
        if rotation_direction == "clockwise":
            min_a, max_a = current_angle, current_angle + sector
        else:
            min_a, max_a = current_angle - sector, current_angle

    candidates = []
    for feat in poi_data.get("features", []):
        poi_id = feat["properties"].get("titre")
        if poi_id in visited_pois:
            continue
        poi_coord = tuple(feat["geometry"]["coordinates"])
        if _is_poi_close_to_path(poi_coord, path_coords, max_distance_m=path_exclusion_m):
            continue
        dist = haversine(current_coord, poi_coord)
        if dist > max_distance or dist < 100:
            continue
        if sector_filter:
            poi_angle = math.atan2(poi_coord[1] - mcy, poi_coord[0] - mcx)
            if not angle_in_sector(poi_angle, min_a, max_a, rotation_direction):
                continue
        candidates.append({
            "id": poi_id, "coord": poi_coord,
            "score": float(feat["properties"].get("score", 0.0)),
            "distance": dist,
        })
    return candidates


def select_best_poi(candidates, randomness):
    """Sélectionne le meilleur POI avec score composite (base + proximité + bruit)."""
    if not candidates:
        return None
    scored = []
    for poi in candidates:
        proximity_bonus = max(0, (5000 - poi["distance"]) / 5000) * 0.3
        scored.append({**poi, "final_score": poi["score"] + proximity_bonus + random.uniform(-randomness, randomness)})
    return max(scored, key=lambda x: x["final_score"])


def extract_pois_near_path(path, poi_data, max_distance_m=200):
    """Extrait les POI à moins de max_distance_m du tracé (distance point-segment)."""
    R = 6371000.0

    def to_xy(lon, lat, lat_ref):
        x = math.radians(lon) * math.cos(math.radians(lat_ref)) * R
        y = math.radians(lat) * R
        return x, y

    def pt_seg_dist(pt, a, b):
        lat_ref = (pt[1] + a[1] + b[1]) / 3.0
        px, py = to_xy(pt[0], pt[1], lat_ref)
        ax, ay = to_xy(a[0], a[1], lat_ref)
        bx, by = to_xy(b[0], b[1], lat_ref)
        vx, vy = bx - ax, by - ay
        wx, wy = px - ax, py - ay
        vlen2 = vx * vx + vy * vy
        if vlen2 == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, (wx * vx + wy * vy) / vlen2))
        return math.hypot(px - (ax + t * vx), py - (ay + t * vy))

    if not path or not poi_data or "features" not in poi_data:
        return []

    near = []
    for feat in poi_data.get("features", []):
        try:
            coords = feat.get("geometry", {}).get("coordinates")
            if not coords or len(coords) < 2:
                continue
            poi = (coords[0], coords[1])
            min_d = float("inf")
            for u, v in zip(path[:-1], path[1:]):
                d = pt_seg_dist(poi, (u[0], u[1]), (v[0], v[1]))
                min_d = min(min_d, d)
                if min_d <= max_distance_m:
                    break
            if min_d <= max_distance_m:
                near.append(feat)
        except Exception:
            continue
    return near
