import geopandas as gpd
from shapely.geometry import Point
import os
from sklearn.preprocessing import MinMaxScaler
import sys
from utils import slugify

def main():
    if len(sys.argv) < 2:
        print("❌ Usage: python Graphe_1_POI_fusion.py <massif_name>")
        sys.exit(1)

    massif_name = sys.argv[1]
    massif_slug = slugify(massif_name)

    # Fichiers
    poi_file = f"data/output/{massif_slug}_poi_scores.geojson"
    paths_file = f"data/intermediate/{massif_slug}_hiking_paths.geojson"
    output_file = f"data/output/{massif_slug}_hiking_paths_with_poi_scores.geojson"

    # Charger
    gdf_poi = gpd.read_file(poi_file)
    gdf_paths = gpd.read_file(paths_file)

    # Afficher le nombre initial de POI
    initial_poi_count = len(gdf_poi)
    print(f"📍 Nombre initial de POI : {initial_poi_count}")

    # Reprojeter en métrique (Lambert 93) pour calculs de distance
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

    # Vérifier que chaque POI a un chemin à moins de 200 mètres
    paths_sindex = gdf_paths.sindex
    poi_to_keep = []
    
    for idx, poi in gdf_poi.iterrows():
        poi_point = poi.geometry
        if poi_point is None:
            continue
        
        buffer = poi_point.buffer(200)  # 200 m
        possible_idxs = list(paths_sindex.intersection(buffer.bounds))
        
        has_nearby_path = False
        for path_idx in possible_idxs:
            path_geom = gdf_paths.at[path_idx, "geometry"]
            if path_geom is not None and buffer.intersects(path_geom):
                has_nearby_path = True
                break
        
        if has_nearby_path:
            poi_to_keep.append(idx)
    
    # Nombre de POI supprimés
    poi_removed_count = len(gdf_poi) - len(poi_to_keep)
    gdf_poi = gdf_poi.loc[poi_to_keep]

    # Index spatial
    paths_sindex = gdf_paths.sindex

    # Initialiser l'agrégation
    gdf_paths["poi_score_total"] = 0.0

    # Pour chaque POI, buffer de 100 m et ajouter son score
    for _, poi in gdf_poi.iterrows():
        poi_point = poi.geometry
        if poi_point is None:
            continue

        try:
            base_score = float(poi.get("score", 0))
        except Exception:
            base_score = 0.0

        if str(poi.get("type", "")).lower() == "summit":
            base_score *= 5  # bonus pour les sommets

        buffer = poi_point.buffer(100)  # 100 m
        possible_idxs = list(paths_sindex.intersection(buffer.bounds))
        if not possible_idxs:
            continue

        for idx in possible_idxs:
            path_geom = gdf_paths.at[idx, "geometry"]
            if path_geom is not None and buffer.intersects(path_geom):
                gdf_paths.at[idx, "poi_score_total"] += base_score

    # Construire score_total
    gdf_paths["randonnabilite_score"] = gdf_paths["randonnabilite_score"].fillna(0.0)
    gdf_paths["score_total"] = gdf_paths["randonnabilite_score"] + gdf_paths["poi_score_total"]
    scaler = MinMaxScaler()
    gdf_paths["score_total_normalized"] = scaler.fit_transform(gdf_paths[["score_total"]])

    # Longueur en mètres
    gdf_paths["distance_meters"] = gdf_paths.geometry.length
    gdf_paths["distance_meters_normalized"] = scaler.fit_transform(gdf_paths[["distance_meters"]])

    # Nettoyage
    gdf_paths = gdf_paths.drop(columns=["randonnabilite_score", "poi_score_total"], errors="ignore")

    # Reprojeter en WGS84
    gdf_paths = gdf_paths.to_crs(epsg=4326)

    # Sauvegarder les chemins
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    gdf_paths.to_file(output_file, driver="GeoJSON")

    # Sauvegarder les POI filtrés
    gdf_poi = gdf_poi.to_crs(epsg=4326)
    os.makedirs(os.path.dirname(poi_file), exist_ok=True)
    gdf_poi.to_file(poi_file, driver="GeoJSON")

    print(f"✅ Résultat des chemins enregistré dans {output_file}")
    print(f"✅ Résultat des POI enregistré dans {poi_file}")
    print(f"🗑️  Nombre de POI supprimés : {poi_removed_count}")


if __name__ == "__main__":
    main()
