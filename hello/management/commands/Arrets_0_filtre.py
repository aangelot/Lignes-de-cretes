import sys
import pandas as pd
import geopandas as gpd
import numpy as np
from sklearn.cluster import DBSCAN
from utils import slugify

def process_arrets(massif: str):
    # 1. Charger le fichier CSV contenant tous les arrêts de transport en commun en France
    df = pd.read_csv("data/input/stops_france.csv", sep=',')

    # 2. Convertir en GeoDataFrame avec les coordonnées (EPSG:4326)
    gdf_stops = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df['stop_lon'], df['stop_lat']),
        crs="EPSG:4326"
    )

    # 3. Reprojeter en Lambert 93 (mètres) pour les calculs spatiaux
    gdf_stops = gdf_stops.to_crs(epsg=2154)

    # 4. Charger les parcs naturels et filtrer celui correspondant au massif
    gdf_parks = gpd.read_file("data/input/PNR.geojson")
    gdf_park = gdf_parks[gdf_parks["DRGP_L_LIB"] == massif].to_crs(epsg=2154)

    if gdf_park.empty:
        raise ValueError(f"Massif '{massif}' introuvable dans PNR.geojson")

    # 5. Sélectionner les arrêts situés à l’intérieur du parc
    gdf_in_park = gpd.sjoin(gdf_stops, gdf_park, how="inner", predicate="within")

    # 6. Supprimer les arrêts scolaires
    gdf_in_park = gdf_in_park[~gdf_in_park["dataset_custom_title"].str.contains("scolaire", case=False, na=False)]

    # 7. Clustering spatial (200 m)
    coords = np.array([(point.x, point.y) for point in gdf_in_park.geometry])
    if len(coords) > 0:
        db = DBSCAN(eps=200, min_samples=1).fit(coords)
        gdf_in_park["cluster"] = db.labels_
        gdf_in_park = gdf_in_park.sort_values("cluster").drop_duplicates("cluster", keep="first")

    # 8. Ajouter les gares SNCF dans un buffer de 2 km autour du parc
    buffer_park = gdf_park.buffer(2000)
    gdf_buffer = gpd.GeoDataFrame(geometry=buffer_park, crs=gdf_park.crs)

    gdf_gares = gdf_stops[
        (gdf_stops["dataset_organisation"].str.contains("SNCF", case=False, na=False))
    ]
    gdf_gares = gpd.sjoin(gdf_gares, gdf_buffer, how="inner", predicate="intersects")

    # 9. Fusionner les arrêts du parc et les gares périphériques
    gdf_final = pd.concat([gdf_in_park, gdf_gares]).drop_duplicates(subset=["stop_id"])

    # 10. Reprojeter en WGS84 pour export GeoJSON
    gdf_final = gdf_final.to_crs(epsg=4326)

    # 11. Exporter le résultat en GeoJSON
    output_path = f"data/intermediate/{slugify(massif)}_arrets.geojson"
    gdf_final.to_file(output_path, driver="GeoJSON")

    print(f"✅ Fichier exporté : {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python Arrets_0_filtre.py <Massif>")
        sys.exit(1)

    massif_name = sys.argv[1]
    process_arrets(massif_name)
