"""
Outils géographiques et géocodage pour la planification de randonnées.
Contient les fonctions de calcul de distances, recherche de noeuds et géocodage d'adresses.
"""

import logging
import math
import random
import requests
from shapely.geometry import LineString

logger = logging.getLogger(__name__)


def geocode_address(address: str):
    """
    Géocode une adresse en latitude/longitude via la Base Adresse Nationale.
    Renvoie [latitude, longitude] si trouvé, sinon None.
    """
    url = "https://api-adresse.data.gouv.fr/search/"
    params = {
        "q": address,
        "limit": 1
    }
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        features = data.get("features", [])
        if features:
            coords = features[0]["geometry"]["coordinates"]
            # API BAN renvoie [lon, lat]
            return [coords[1], coords[0]]
        return None
    except Exception as e:
        logger.info(f"Erreur géocodage adresse '{address}': {e}")
        return None


def haversine(coord1, coord2):
    """Distance (m) entre deux points (lat, lon)."""
    R = 6371000
    lat1, lon1 = map(math.radians, coord1)
    lat2, lon2 = map(math.radians, coord2)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 2 * R * math.asin(math.sqrt(a))


def find_nearest_node(G, coord):
    """Trouve le nœud du graphe le plus proche d'une coordonnée (lat, lon)."""
    # Si le graphe a été filtré pour ne contenir que la plus grande composante,
    # tous les nœuds sont connectés. Sinon, on prend le plus proche parmi tous.
    return min(G.nodes, key=lambda n: haversine(coord, (n[1], n[0])))


def _angle_between(p1, p2, p3):
    """Cosinus de l'angle entre (p1→p2) et (p2→p3)."""
    v1 = (p2[0] - p1[0], p2[1] - p1[1])
    v2 = (p3[0] - p2[0], p3[1] - p2[1])
    dot = v1[0]*v2[0] + v1[1]*v2[1]
    norm1 = math.sqrt(v1[0]**2 + v1[1]**2)
    norm2 = math.sqrt(v2[0]**2 + v2[1]**2)
    if norm1 == 0 or norm2 == 0:
        return 0
    cos_theta = dot / (norm1 * norm2)
    return max(-1.0, min(1.0, cos_theta))


def determine_rotation_direction():
    return random.choice(["clockwise", "counterclockwise"])


def angle_in_sector(poi_angle, min_angle, max_angle, direction):
    """Vérifie si un angle est dans le secteur angulaire, avec gestion du wrap-around."""
    def norm(a):
        while a > math.pi: a -= 2 * math.pi
        while a < -math.pi: a += 2 * math.pi
        return a
    pa, mina, maxa = norm(poi_angle), norm(min_angle), norm(max_angle)
    if mina <= maxa:
        return mina <= pa <= maxa
    return pa >= mina or pa <= maxa


def _path_has_crossing(path_nodes, new_segment_nodes):
    """Retourne True si le nouveau segment croise le chemin existant."""
    if len(path_nodes) < 2 or len(new_segment_nodes) < 2:
        return False
    current_line = LineString(path_nodes)
    new_line = LineString(new_segment_nodes)
    return current_line.crosses(new_line)


# --- Utilitaires graphe ---

from hello.constants import REUSE_PENALTY_MULTIPLIER


def save_original_weights(G):
    """Sauvegarde les poids originaux du graphe (avant pénalisation)."""
    weights = {}
    for u, v, data in G.edges(data=True):
        weights[(u, v)] = data.get("length", 1.0)
        weights[(v, u)] = data.get("length", 1.0)
    return weights


def restore_original_weights(G, original_weights):
    """Restaure les poids originaux dans le graphe."""
    for u, v, data in G.edges(data=True):
        if (u, v) in original_weights:
            G[u][v]["length"] = original_weights[(u, v)]


def get_path_length(G, path_nodes):
    """Calcule la distance totale d'un chemin de nœuds."""
    if len(path_nodes) < 2:
        return 0
    return sum(G[u][v]["length"] for u, v in zip(path_nodes[:-1], path_nodes[1:]))


def get_path_coordinates(G, path_nodes):
    """Extrait les coordonnées (lon, lat) d'un chemin de nœuds."""
    coords = []
    for node in path_nodes:
        if isinstance(node, tuple) and len(node) >= 2:
            coords.append(node)
        elif node in G.nodes:
            data = G.nodes[node]
            if "pos" in data:
                coords.append(data["pos"])
            elif "lon" in data and "lat" in data:
                coords.append((data["lon"], data["lat"]))
    return coords


def penalize_path_edges(G, path_nodes, original_weights, penalty_multiplier=None):
    """Pénalise les arêtes d'un chemin pour dissuader leur réutilisation."""
    if penalty_multiplier is None:
        penalty_multiplier = REUSE_PENALTY_MULTIPLIER
    used_edges = {}
    for i in range(len(path_nodes) - 1):
        u, v = path_nodes[i], path_nodes[i + 1]
        edge_key = (u, v) if (u, v) in original_weights else (v, u)
        count = used_edges.get(edge_key, 0)
        used_edges[edge_key] = count + 1
        new_weight = original_weights[edge_key] * (1 + penalty_multiplier * (count + 1))
        if G.has_edge(u, v):
            G[u][v]["length"] = new_weight
        if G.has_edge(v, u):
            G[v][u]["length"] = new_weight


