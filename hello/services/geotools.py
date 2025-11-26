"""
Outils géographiques et géocodage pour la planification de randonnées.
Contient les fonctions de calcul de distances, recherche de noeuds,
géocodage d'adresses et sauvegarde de fichiers géographiques.
"""

import json
import math
import os
import requests
import gpxpy
import gpxpy.gpx
from shapely.geometry import LineString, mapping, shape


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
        print(f"Erreur géocodage adresse '{address}': {e}")
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
    return min(G.nodes, key=lambda n: haversine(coord, (n[1], n[0])))


def angle_between(p1, p2, p3):
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


def path_has_crossing(path_nodes, new_segment_nodes):
    """
    Retourne True si le nouveau segment croise le chemin existant.
    """
    if len(path_nodes) < 2 or len(new_segment_nodes) < 2:
        return False

    current_line = LineString(path_nodes)
    new_line = LineString(new_segment_nodes)
    return current_line.crosses(new_line)


def save_geojson_gpx(data, output_path="hello/static/hello/data/optimized_routes.geojson"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        print(f"✅ GeoJSON sauvegardé dans {output_path}")
    with open(output_path, "r") as f:
        geojson_data = json.load(f)
    gpx = gpxpy.gpx.GPX()
    for feature in geojson_data["features"]:
        geom = shape(feature["geometry"])
        if geom.geom_type == "LineString":
            track = gpxpy.gpx.GPXTrack()
            gpx.tracks.append(track)
            segment = gpxpy.gpx.GPXTrackSegment()
            track.segments.append(segment)

            for coord in geom.coords:
                lon, lat = coord[0], coord[1]
                ele = coord[2] if len(coord) > 2 else None  # récupère l'altitude si présente
                segment.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon, elevation=ele))

    # Sauver en GPX
    with open("hello/static/hello/data/optimized_routes.gpx", "w") as f:
        f.write(gpx.to_xml())
