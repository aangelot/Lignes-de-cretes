import geopandas as gpd
from shapely.geometry import Point, LineString
import os
from sklearn.preprocessing import MinMaxScaler
from pyproj import Geod

# Fichiers
POI_FILE = "data/intermediate/poi_scores.geojson"
PATHS_FILE = "data/intermediate/chartreuse_hiking_paths.geojson"
OUTPUT_FILE = "data/output/chartreuse_hiking_paths_with_poi_scores.geojson"

# Charger
gdf_poi = gpd.read_file(POI_FILE)
gdf_paths = gpd.read_file(PATHS_FILE)

# Reprojecter en métrique (Lambert 93) pour calculs de distance
gdf_poi = gdf_poi.to_crs(epsg=2154)
gdf_paths = gdf_paths.to_crs(epsg=2154)

# S'assurer que POI ont une géométrie
if "geometry" not in gdf_poi.columns or gdf_poi.geometry.is_empty.all():
    def make_point(row):
        geo = row.get("geolocalisation", None)
        if geo and isinstance(geo, (list, tuple)) and len(geo) >= 2:
            return Point(geo[0], geo[1])
        return None
    gdf_poi["geometry"] = gdf_poi.apply(make_point, axis=1)
    gdf_poi = gdf_poi.set_geometry("geometry")

# Initialiser l'agrégation
gdf_paths["poi_score_total"] = 0.0

# Index spatial pour les chemins (facultatif mais accélère l'intersection)
paths_sindex = gdf_paths.sindex

# Pour chaque POI, buffer de 100 m et ajouter son score à tous les segments intersectés
for _, poi in gdf_poi.iterrows():
    poi_point = poi.geometry
    if poi_point is None:
        continue

    try:
        base_score = float(poi.get("score", 0))
    except Exception:
        base_score = 0.0

    if str(poi.get("type", "")).lower() == "summit":
        base_score *= 5

    buffer = poi_point.buffer(100)  # 100 mètres

    # Recherche rapide d'éventuels candidats via spatial index
    possible_idxs = list(paths_sindex.intersection(buffer.bounds))
    if not possible_idxs:
        continue

    # Pour chaque segment qui intersecte réellement
    for idx in possible_idxs:
        path_geom = gdf_paths.at[idx, "geometry"]
        if path_geom is not None and buffer.intersects(path_geom):
            gdf_paths.at[idx, "poi_score_total"] += base_score

# Construire score_total
gdf_paths["randonnabilite_score"] = gdf_paths["randonnabilite_score"].fillna(0.0)
gdf_paths["score_total"] = gdf_paths["randonnabilite_score"] + gdf_paths["poi_score_total"]
scaler = MinMaxScaler()
gdf_paths["score_total_normalized"] = scaler.fit_transform(gdf_paths[["score_total"]])

# Calcul de la longueur en mètres pour chaque LineString
gdf_paths["distance_meters"] = gdf_paths.geometry.length
gdf_paths["distance_meters_normalized"] = scaler.fit_transform(gdf_paths[["distance_meters"]])

# Supprimer les anciens champs
gdf_paths = gdf_paths.drop(columns=["randonnabilite_score"])
gdf_paths = gdf_paths.drop(columns=["poi_score_total"])


# Reprojeter en WGS84 si tu veux revenir à exploitable en front
gdf_paths = gdf_paths.to_crs(epsg=4326)

# Sauvegarder
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
gdf_paths.to_file(OUTPUT_FILE, driver="GeoJSON")

print(f"✅ Résultat enregistré dans {OUTPUT_FILE}")

