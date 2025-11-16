# Graphe_0_overpy.py
import sys
from pathlib import Path
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import unary_union
import overpy
from utils import slugify
import pandas as pd
import http.client

def score_randonnabilite(attrs):
    """Attribue un score de 'randonnabilité' à une voie en fonction de ses attributs OSM."""
    hw = attrs.get("highway", "")
    foot = attrs.get("foot", None)
    sac = attrs.get("sac_scale", None)

    if hw in ["motorway", "trunk", "primary"]:
        return 0.1
    elif hw in ["secondary", "tertiary", "unclassified", "residential"]:
        return 0.2
    elif hw in ["track", "service"]:
        return 0.5
    elif hw in ["footway", "path"]:
        if foot in ["yes", "permissive", "designated"]:
            return 1.0
        return 0.9
    elif sac in ["hiking", "mountain_hiking"]:
        return 1.0
    return 0.2

def polygon_to_bbox(poly: Polygon):
    """Convertit un polygone Shapely en bbox compatible Overpass: (south, west, north, east)"""
    minx, miny, maxx, maxy = poly.bounds
    return miny, minx, maxy, maxx

def split_bbox(bbox, n=2):
    """Découpe une bbox (south, west, north, east) en n*n sous-bbox"""
    south, west, north, east = bbox
    lat_step = (north - south) / n
    lon_step = (east - west) / n
    boxes = []
    for i in range(n):
        for j in range(n):
            boxes.append((
                south + i * lat_step,
                west + j * lon_step,
                south + (i + 1) * lat_step,
                west + (j + 1) * lon_step
            ))
    return boxes

def main(massif_name: str):
    # Charger le massif depuis le fichier PNR.geojson
    gdf_parks = gpd.read_file("data/input/PNR.geojson")
    gdf_massif = gdf_parks[gdf_parks["DRGP_L_LIB"] == massif_name]

    if gdf_massif.empty:
        print(f"❌ Massif '{massif_name}' introuvable dans PNR.geojson")
        sys.exit(1)

    # Buffer de 2 km et projection
    gdf_massif = gdf_massif.to_crs(epsg=2154)
    gdf_buffered = gdf_massif.buffer(2000)
    gdf_buffered = gdf_buffered.to_crs(epsg=4326)

    geometry_union = unary_union(gdf_buffered.geometry)
    south, west, north, east = polygon_to_bbox(geometry_union)

    # Fractionner la bbox si nécessaire (ex: 2x2 = 4 sous-bbox)
    sub_bboxes = split_bbox((south, west, north, east), n=2)

    # Création de l'API Overpass avec timeout plus long
    api = overpy.Overpass(url="https://overpass-api.de/api/interpreter")
    all_rows = []

    for bbox in sub_bboxes:
        s, w, n, e = bbox
        query = f"""
        [out:json][timeout:600];
        (
          way["highway"]({s},{w},{n},{e});
        );
        out body;
        >;
        out skel qt;
        """

        # Retry automatique
        for attempt in range(3):
            try:
                print(f"📡 Appel Overpass pour bbox {bbox} (tentative {attempt+1})…")
                result = api.query(query)
                break
            except (overpy.exception.OverpassGatewayTimeout,
                    overpy.exception.OverpassTooManyRequests,
                    http.client.IncompleteRead) as e:
                print(f"⚠️ Erreur Overpass: {e}, retry dans 5s…")
                import time
                time.sleep(5)
        else:
            print(f"❌ Échec après 3 tentatives pour bbox {bbox}")
            continue

        # Extraire les ways
        for way in result.ways:
            try:
                coords = [(float(node.lon), float(node.lat)) for node in way.nodes]
                geom = LineString(coords)
                if not geom.intersects(geometry_union):
                    continue
                attrs = way.tags
                score = score_randonnabilite(attrs)
                all_rows.append({"geometry": geom, "randonnabilite_score": score})
            except Exception as e:
                print(f"⚠️ Erreur sur un way: {e}")

    if not all_rows:
        print("❌ Aucun chemin récupéré")
        sys.exit(1)

    gdf_edges = gpd.GeoDataFrame(all_rows, crs="EPSG:4326")

    # Sauvegarde
    massif_slug = slugify(massif_name)
    output_path = Path("data/intermediate") / f"{massif_slug}_hiking_paths.geojson"
    gdf_edges.to_file(output_path, driver="GeoJSON")
    print(f"✔️ Graphe sauvegardé dans {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Utilisation : python Graphe_0_overpy.py '<Nom du massif>'")
        sys.exit(1)
    massif_name = sys.argv[1]
    main(massif_name)
