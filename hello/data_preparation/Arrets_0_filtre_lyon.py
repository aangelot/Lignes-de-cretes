import sys
import pandas as pd
import geopandas as gpd
import numpy as np
from sklearn.cluster import DBSCAN
from utils import slugify

def process_arrets(massif: str):
    # 1. Charger le fichier CSV du réseau TCL (Lyon)
    df = pd.read_csv(
        "data/input/stops_reseau_transports_commun_lyonnais.csv",
        sep=';'
    )

    # Forcer les colonnes de coordonnées à utiliser un point décimal
    df["lon"] = df["lon"].astype(str).str.replace(",", ".", regex=False).astype(float)
    df["lat"] = df["lat"].astype(str).str.replace(",", ".", regex=False).astype(float)


    # Renommer les colonnes pour correspondre au schéma utilisé dans le script original
    df = df.rename(columns={
        "id": "stop_id",
        "nom": "stop_name",
        "lon": "stop_lon",
        "lat": "stop_lat",
    })

    # 2. Convertir en GeoDataFrame (EPSG:4326)
    gdf_stops = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["stop_lon"], df["stop_lat"]),
        crs="EPSG:4326"
    )

    # 3. Reprojeter en Lambert 93 pour les calculs spatiaux
    gdf_stops = gdf_stops.to_crs(epsg=2154)

    # 4. Charger les parcs naturels et filtrer celui correspondant au massif
    gdf_parks = gpd.read_file("data/input/massifs.geojson")
    gdf_park = gdf_parks[gdf_parks["DRGP_L_LIB"] == massif].to_crs(epsg=2154)

    if gdf_park.empty:
        raise ValueError(f"Massif '{massif}' introuvable dans massifs.geojson")

    # 5. Sélectionner les arrêts situés dans le parc
    gdf_in_park = gpd.sjoin(gdf_stops, gdf_park, how="inner", predicate="within")

    # 6. Clustering spatial (200 m)
    coords = np.array([(pt.x, pt.y) for pt in gdf_in_park.geometry])
    if len(coords) > 0:
        db = DBSCAN(eps=200, min_samples=1).fit(coords)
        gdf_in_park["cluster"] = db.labels_
        gdf_in_park = gdf_in_park.sort_values("cluster").drop_duplicates("cluster", keep="first")

    # 7. Reprojeter pour export
    gdf_final = gdf_in_park.to_crs(epsg=4326)

    # 8. Export
    output_path = f"data/intermediate/{slugify(massif)}_arrets.geojson"
    gdf_final.to_file(output_path, driver="GeoJSON")

    print(f"Fichier exporté : {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python Arrets_0_filtre_lyon.py <Massif>")
        sys.exit(1)

    massif_name = sys.argv[1]
    process_arrets(massif_name)
