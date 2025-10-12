# Graphe_0.py
import osmnx as ox
import geopandas as gpd
from pathlib import Path
import sys
from shapely.ops import unary_union
from utils import slugify  # même utilitaire que dans main.py

def score_randonnabilite(row):
    """Attribue un score de 'randonnabilité' à une voie en fonction de ses attributs OSM."""
    hw = row.get("highway", "")
    foot = row.get("foot", None)
    sac = row.get("sac_scale", None)

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

def main(massif_name: str):
    # Charger le massif depuis le fichier PNR.geojson
    gdf_parks = gpd.read_file("data/input/PNR.geojson")
    gdf_massif = gdf_parks[gdf_parks["DRGP_L_LIB"] == massif_name]

    if gdf_massif.empty:
        print(f"❌ Massif '{massif_name}' introuvable dans PNR.geojson")
        sys.exit(1)

    # Projection en Lambert 93 pour le buffer puis retour en WGS84
    gdf_massif = gdf_massif.to_crs(epsg=2154)
    gdf_buffered = gdf_massif.buffer(2000)  # buffer de 2 km autour
    gdf_buffered = gdf_buffered.to_crs(epsg=4326)

    # Télécharger les linéaires OSM
    tags = {"highway": True}
    geometry_union = gdf_buffered.geometry.union_all()
    gdf_edges = ox.features_from_polygon(geometry_union, tags)

    # Filtrer uniquement les LineString et MultiLineString
    gdf_edges = gdf_edges[gdf_edges.geometry.type.isin(["LineString", "MultiLineString"])]

    # Appliquer le score
    gdf_edges["randonnabilite_score"] = gdf_edges.apply(score_randonnabilite, axis=1)

    # Garder uniquement la géométrie + score
    gdf_simplified = gdf_edges[["geometry", "randonnabilite_score"]]

    # Sauvegarde
    massif_slug = slugify(massif_name)
    output_path = Path("data/intermediate") / f"{massif_slug}_hiking_paths.geojson"
    gdf_simplified.to_file(output_path, driver="GeoJSON")
    print(f"✔️ Graphe sauvegardé dans {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Utilisation : python Graphe_0.py '<Nom du massif>'")
        sys.exit(1)
    massif_name = sys.argv[1]
    main(massif_name)
