import osmnx as ox
import geopandas as gpd
from shapely.ops import unary_union 

# 1. Charger la commune du Sappey-en-Chartreuse et buffer
pnr_name = "Parc naturel régional de Chartreuse, France"
gdf_pnr = ox.geocode_to_gdf(pnr_name)
gdf_pnr = gdf_pnr.to_crs(epsg=2154)
gdf_buffered = gdf_pnr.buffer(2000)
gdf_buffered = gdf_buffered.to_crs(4326)

# 2. Télécharger tous les linéaires avec le tag "highway"
tags = {"highway": True}
geometry_union = gdf_buffered.geometry.union_all()
gdf_edges = ox.features_from_polygon(geometry_union, tags)

# 3. Scoring fonction
def score_randonnabilite(row):
    hw = row.get("highway", "")
    foot = row.get("foot", None)
    sac = row.get("sac_scale", None)

    if hw in ["motorway", "trunk", "primary"]:
        return 0.1
    elif hw in ["secondary", "tertiary", "unclassified", "residential"]:
        return 0.2
    elif hw in ["track", "service"]:
        return 0.5
    elif hw in ["footway", "path"] :
        return 0.9
    elif hw in ["footway", "path"] and foot in ["yes", "permissive", "designated"]:
        return 1.0
    elif sac in ["hiking", "mountain_hiking"]:
        return 1.0
    return 0.2

# 4. Filtrer les linéaires (LineString ou MultiLineString uniquement)
gdf_edges = gdf_edges[gdf_edges.geometry.type.isin(["LineString", "MultiLineString"])]

# 5. Appliquer le score
gdf_edges["randonnabilite_score"] = gdf_edges.apply(score_randonnabilite, axis=1)

# 6. Garder uniquement la géométrie et le score
gdf_simplified = gdf_edges[["geometry", "randonnabilite_score"]]

# 7. Sauvegarde du fichier
output_path = "data/intermediate/chartreuse_hiking_paths.geojson"
gdf_simplified.to_file(output_path, driver="GeoJSON")
print(f"✔️ Données sauvegardées dans {output_path}")