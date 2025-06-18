import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import numpy as np
from sklearn.cluster import DBSCAN

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

# 4. Charger les parcs naturels et filtrer celui de la Chartreuse
gdf_parks = gpd.read_file("data/input/PNR.geojson")
gdf_park = gdf_parks[gdf_parks["DRGP_L_LIB"] == "Chartreuse"].to_crs(epsg=2154)

# 5. Créer une zone tampon de 2 km autour du parc
buffer_park = gdf_park.buffer(2000)
gdf_buffer = gpd.GeoDataFrame(geometry=buffer_park, crs=gdf_park.crs)

# 6. Sélectionner les arrêts situés dans la zone tampon
gdf_filtered = gpd.sjoin(gdf_stops, gdf_buffer, how="inner", predicate="intersects")

# 7. Supprimer les arrêts à vocation scolaire
gdf_filtered = gdf_filtered[~gdf_filtered["dataset_custom_title"].str.contains("scolaire", case=False, na=False)]

# 8. Regrouper les arrêts distants de moins de 200 mètres (clustering spatial)
coords = np.array([(point.x, point.y) for point in gdf_filtered.geometry])
db = DBSCAN(eps=200, min_samples=1).fit(coords)
gdf_filtered["cluster"] = db.labels_

# 9. Conserver un seul arrêt représentatif par cluster (le premier)
gdf_unique = gdf_filtered.sort_values("cluster").drop_duplicates("cluster", keep="first")

# 10. Reprojeter en WGS84 pour export GeoJSON
gdf_unique = gdf_unique.to_crs(epsg=4326)

# 11. Exporter le résultat en GeoJSON
gdf_unique.to_file("data/intermediate/1_chartreuse_arrets.geojson", driver="GeoJSON")

