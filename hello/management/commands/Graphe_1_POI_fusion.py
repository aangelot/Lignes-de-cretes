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

    # Initialiser l'agrégation
    gdf_paths["poi_score_total"] = 0.0

    # Index spatial
    paths_sindex = gdf_paths.sindex

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

    # Sauvegarder
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    gdf_paths.to_file(output_file, driver="GeoJSON")

    print(f"✅ Résultat enregistré dans {output_file}")


if __name__ == "__main__":
    main()
