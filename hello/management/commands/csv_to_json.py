import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

# 1. Charger le fichier CSV contenant les arrêts uniques
df = pd.read_csv("data/intermediate/stops_chartreuse_unique.csv")

# 2. Créer une colonne 'geometry' avec les coordonnées (latitude et longitude)
geometry = [Point(xy) for xy in zip(df['stop_lon'], df['stop_lat'])]

# 3. Convertir en GeoDataFrame
gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:2154")

# 4. Exporter en format GeoJSON
gdf.to_file("data/intermediate/stops_chartreuse_unique.geojson", driver="GeoJSON")
