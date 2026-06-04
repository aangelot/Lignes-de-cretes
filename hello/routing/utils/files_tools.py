"""
Chargement des fichiers de données associés à un massif, construction et sauvegarde du résultat.
"""

import json
import logging
import os
import pickle
from datetime import datetime

logger = logging.getLogger(__name__)

import gpxpy
import gpxpy.gpx
from shapely.geometry import LineString, mapping, shape
from django.conf import settings

from hello.data_preparation.utils import slugify


def load_massif_data(massif_name: str) -> dict:
    """
    Charge les fichiers de données d'un massif et les retourne dans un dict.

    Retourne: {stops_data, stops_path, G, poi_data, hubs_entree_data}
    Lève FileNotFoundError si un fichier est manquant.
    """
    massif_clean = slugify(massif_name)

    files = {
        "stops": f"data/output/{massif_clean}_arrets_stop_node_mapping.json",
        "graph": f"data/output/{massif_clean}_hiking_graph.gpickle",
        "poi": f"data/output/{massif_clean}_poi_scores.geojson",
        "hubs": f"data/output/{massif_clean}_hubs_entree.geojson",
    }

    for path in files.values():
        if not os.path.exists(path):
            raise FileNotFoundError(f"Fichier introuvable : {path}")

    with open(files["stops"], "r", encoding="utf-8") as f:
        stops_data = json.load(f)

    with open(files["graph"], "rb") as f:
        G = pickle.load(f)

    with open(files["poi"], "r", encoding="utf-8") as f:
        poi_data = json.load(f)

    with open(files["hubs"], "r", encoding="utf-8") as f:
        hubs_entree_data = json.load(f)

    return {
        "stops_data": stops_data,
        "stops_path": files["stops"],
        "G": G,
        "poi_data": poi_data,
        "hubs_entree_data": hubs_entree_data,
    }


def build_geojson(path, dist, route_type, travel_go, travel_return,
                  total_ascent, elevation_failed, return_error_message, poi_data):
    from hello.routing.utils.poi_tools import extract_pois_near_path

    extra_props = {}
    if elevation_failed:
        extra_props["elevation_error"] = True
    if return_error_message:
        extra_props["return_error"] = True
        extra_props["return_error_message"] = return_error_message

    try:
        near_pois = extract_pois_near_path(path, poi_data, max_distance_m=200)
    except Exception as e:
        logger.warning(f"erreur POI : {e}")
        near_pois = []

    props = {
        "start_coord": path[0] if path else None,
        "end_coord": path[-1] if path else None,
        "path_length": dist,
        "route_type": route_type,
        "transit_go": travel_go,
        "transit_back": travel_return,
        "path_elevation": total_ascent,
        "near_pois": near_pois,
        **extra_props,
    }
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": mapping(LineString(path)), "properties": props}],
    }


def _save_geojson_gpx(data, output_path="hello/static/hello/data/optimized_routes.geojson"):
    """Sauvegarde le GeoJSON dans output_path et génère un fichier GPX au même emplacement."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        logger.info(f"GeoJSON sauvegardé dans {output_path}")

    try:
        with open(output_path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
    except Exception:
        geojson_data = data

    gpx = gpxpy.gpx.GPX()
    for feature in geojson_data.get("features", []):
        geom = shape(feature["geometry"])
        if geom.geom_type == "LineString":
            track = gpxpy.gpx.GPXTrack()
            gpx.tracks.append(track)
            segment = gpxpy.gpx.GPXTrackSegment()
            track.segments.append(segment)
            for coord in geom.coords:
                lon, lat = coord[0], coord[1]
                ele = coord[2] if len(coord) > 2 else None
                segment.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon, elevation=ele))

    gpx_path = os.path.splitext(output_path)[0] + ".gpx"
    try:
        with open(gpx_path, "w", encoding="utf-8") as f:
            f.write(gpx.to_xml())
        logger.info(f"GPX sauvegardé dans {gpx_path}")
    except Exception as e:
        logger.info(f"Erreur lors de la sauvegarde du GPX: {e}")


def save_result(result, address, massif_clean, level, randomness, status_callback):
    from hello.routing.domain.progress import update_status

    try:
        params_part = f"{slugify(address)}_{massif_clean}_{slugify(level)}_r{int(randomness*100)}"
    except Exception:
        params_part = f"{slugify(address)}_{massif_clean}"

    ts_ms = int(datetime.utcnow().timestamp() * 1000)
    filename_base = f"route_{params_part}_{ts_ms}"
    output_dir = os.path.join(settings.BASE_DIR, "hello", "static", "hello", "data")
    os.makedirs(output_dir, exist_ok=True)

    try:
        _save_geojson_gpx(result, output_path=os.path.join(output_dir, f"{filename_base}.geojson"))
        result["generated_filename"] = f"{filename_base}.geojson"
        update_status("Sauvegarde terminée", status_callback, 98)
    except Exception as e:
        logger.warning(f"erreur sauvegarde : {e}")
        update_status(f"Erreur de sauvegarde : {e}", status_callback, 98)
