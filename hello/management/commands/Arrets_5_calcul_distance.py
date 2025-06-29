import geopandas as gpd
from shapely.geometry import Point
from shapely.ops import nearest_points

# Charger les 10 premiers arrêts
gdf_stops = gpd.read_file("data/intermediate/chartreuse_scores.geojson")

# Charger uniquement le parc de la Chartreuse
gdf_pnr = gpd.read_file("data/input/PNR.geojson")
gdf_chartreuse = gdf_pnr[gdf_pnr["DRGP_L_LIB"] == "Chartreuse"]

# Vérifier qu'on a bien un polygone
if gdf_chartreuse.empty:
    raise ValueError("Le parc de la Chartreuse est introuvable dans le fichier PNR.geojson")

# Reprojection en Lambert 93 (EPSG:2154) pour un calcul de distance en mètres
gdf_stops = gdf_stops.to_crs(epsg=2154)
gdf_chartreuse = gdf_chartreuse.to_crs(epsg=2154)

# Fusion du polygone du parc et de sa frontière
chartreuse_union = gdf_chartreuse.geometry.union_all()
chartreuse_border = chartreuse_union.boundary

# Fonction de calcul de distance signée
def signed_distance_to_border(point, polygon, border):
    dist = point.distance(border)
    return dist if polygon.contains(point) else -dist

# Application à chaque géométrie
gdf_stops["distance_to_pnr_border"] = gdf_stops.geometry.apply(
    lambda point: signed_distance_to_border(point, chartreuse_union, chartreuse_border)
)

# Sauvegarde
gdf_stops.to_file("data/output/chartreuse_scores_final.geojson", driver="GeoJSON")
print("Fichier exporté : data/output/chartreuse_scores_final.geojson")
