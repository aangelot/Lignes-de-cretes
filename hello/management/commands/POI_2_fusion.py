import json
import geopandas as gpd
from shapely.geometry import Point
from shapely.ops import unary_union
import argparse
import os
import sys
from utils import slugify

# --- Argument massif ---
parser = argparse.ArgumentParser(description="Fusion sommets OSM et POI Google Maps")
parser.add_argument("massif", help="Nom du massif (ex: Chartreuse, Massif Des Bauges)")
args = parser.parse_args()
massif_name = args.massif

# Slug du massif (uniformisation des fichiers)
slug_massif = slugify(massif_name)

# --- Fichiers d'entrée ---
sommets_path = f"data/intermediate/{slug_massif}_sommets_osm.geojson"
poi_path = f"data/intermediate/{slug_massif}_poi_google_maps.geojson"
pnr_path = "data/input/PNR.geojson"

# --- Vérification existence ---
for path in [sommets_path, poi_path, pnr_path]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ Fichier introuvable : {path}")

# --- Chargement des fichiers ---
with open(sommets_path, "r", encoding="utf-8") as f:
    sommets_data = json.load(f)

with open(poi_path, "r", encoding="utf-8") as f:
    poi_data = json.load(f)

pnr = gpd.read_file(pnr_path)
pnr = pnr[pnr["DRGP_L_LIB"].str.lower() == massif_name.lower()]
if pnr.empty:
    raise ValueError(f"❌ Aucun PNR trouvé pour le massif '{massif_name}' dans {pnr_path}")

pnr = pnr.to_crs(epsg=2154)  # Projection métrique pour buffer

# --- Traitement des sommets OSM ---
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
        "type": properties.get("primaryType", None),
        "googlemapsURI": properties.get("googleMapsUri", None),
        "rating": properties.get("rating", None),
        "photo": properties.get("photo", None),
        "elevation": None
    })

# --- Fusion des deux jeux de données ---
merged = sommets_features + poi_features
gdf = gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:4326").to_crs(epsg=2154)

# --- Nettoyage des types inutiles ---
types_a_exclure = [
    "sports_club", "parking", "travel_agency", "wedding_venue",
    "library", "general_contractor", "florist",
    "campground", "adventure_sports_center", None
]
gdf = gdf[~gdf["type"].isin(types_a_exclure)]

# --- Application du buffer autour du PNR ---
pnr_buffer = pnr.buffer(1000)
pnr_union = unary_union(pnr_buffer)
filtered = gdf[gdf.geometry.within(pnr_union)]

# --- Retour en WGS84 ---
filtered = filtered.to_crs(epsg=4326)

# --- Sauvegarde ---
os.makedirs("data/intermediate", exist_ok=True)
output_path = f"data/intermediate/{slug_massif}_poi_fusionnes.geojson"
filtered.to_file(output_path, driver="GeoJSON", encoding="utf-8")

print(f"✅ Fichier fusionné et filtré enregistré dans : {output_path} ({len(filtered)} entrées)")
