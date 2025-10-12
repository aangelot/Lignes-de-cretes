# Arrets_4_distance_bord.py
import geopandas as gpd
from shapely.ops import unary_union
import sys
from utils import slugify

def add_distance_to_border(massif: str, ville: str):
    # Fichier d'entrée et sortie
    file_path = f"data/intermediate/{slugify(massif)}_{slugify(ville)}_arrets.geojson"
    gdf_stops = gpd.read_file(file_path)

    # Charger le parc correspondant
    gdf_pnr = gpd.read_file("data/input/PNR.geojson")
    gdf_massif = gdf_pnr[gdf_pnr["DRGP_L_LIB"] == massif]
    if gdf_massif.empty:
        raise ValueError(f"Le parc du massif '{massif}' est introuvable dans PNR.geojson")

    # Reprojection en Lambert 93 pour le calcul en mètres
    gdf_stops = gdf_stops.to_crs(epsg=2154)
    gdf_massif = gdf_massif.to_crs(epsg=2154)

    # Fusion du polygone du parc et de sa frontière
    massif_union = unary_union(gdf_massif.geometry)
    massif_border = massif_union.boundary

    # Fonction de distance signée
    def signed_distance_to_border(point):
        dist = point.distance(massif_border)
        return dist if massif_union.contains(point) else -dist

    # Application à chaque géométrie
    gdf_stops["distance_to_pnr_border"] = gdf_stops.geometry.apply(signed_distance_to_border)

    # Reprojection en WGS84 pour export
    gdf_stops = gdf_stops.to_crs(epsg=4326)

    # Sauvegarde
    gdf_stops.to_file(file_path, driver="GeoJSON")
    print(f"✅ Fichier exporté : {file_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python Arrets_4_distance_bord.py <Massif> <Ville>")
        sys.exit(1)

    massif_name = sys.argv[1]
    ville_name = sys.argv[2]
    add_distance_to_border(massif_name, ville_name)
