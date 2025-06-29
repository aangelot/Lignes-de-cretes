import json
import geopandas as gpd
from shapely.geometry import Point
from shapely.ops import unary_union

# --- Chargement des fichiers GeoJSON ---

# Sommets OSM
with open("data/input/sommets_chartreuse_osm.geojson", "r", encoding="utf-8") as f:
    sommets_data = json.load(f)

# POI Google Maps
with open("data/input/poi_googlemaps_chartreuse.geojson", "r", encoding="utf-8") as f:
    poi_data = json.load(f)

# PNR (pour filtre spatial)
pnr = gpd.read_file("data/input/PNR.geojson")
pnr = pnr[pnr["DRGP_L_LIB"] == "Chartreuse"]
pnr = pnr.to_crs(epsg=2154)  # Projection métrique pour buffer

# --- Traitement des sommets ---
sommets_features = []
for feat in sommets_data["features"]:
    coord = feat["geometry"]["coordinates"]
    properties = feat["properties"]
    sommets_features.append({
        "geometry": Point(coord),
        "geolocalisation": coord,
        "titre": properties.get("name", ""),
        "type": "summit",
        "googlemapsURI": None,
        "rating": None,
        "photo": None,
        "elevation": properties.get("elevation", None)
    })

# --- Traitement des POI Google Maps ---
poi_features = []
for feat in poi_data["features"]:
    coord = feat["geometry"]["coordinates"]
    properties = feat["properties"]
    poi_features.append({
        "geometry": Point(coord),
        "geolocalisation": coord,
        "titre": properties.get("title", ""),
        "type": properties.get("primaryType", ""),
        "googlemapsURI": properties.get("googleMapsUri", None),
        "rating": properties.get("rating", None),
        "photo": properties.get("photo", None),
        "elevation": None
    })

# --- Fusion des deux listes ---
merged = sommets_features + poi_features

# --- Conversion en GeoDataFrame ---
gdf = gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:4326")
gdf = gdf.to_crs(epsg=2154)

types_a_exclure = [
    "sports_club", "parking", "travel_agency", "wedding_venue",
    "library", "general_contractor", "florist",
    "campground", "adventure_sports_center"
]

# Suppression des entrées dont le type est dans la liste
gdf = gdf[~gdf["type"].isin(types_a_exclure)]

# --- Application du buffer de 1 km autour du PNR ---
pnr_buffer = pnr.buffer(1000)
pnr_union = unary_union(pnr_buffer)

# --- Filtrage spatial ---
filtered = gdf[gdf.geometry.within(pnr_union)]

# --- Retour au CRS WGS84 pour l'export GeoJSON ---
filtered = filtered.to_crs(epsg=4326)

# --- Enregistrement du fichier ---
output_path = "data/intermediate/poi_fusionnes.geojson"
filtered.to_file(output_path, driver="GeoJSON", encoding="utf-8")

print(f"Fichier fusionné et filtré enregistré dans : {output_path}")
