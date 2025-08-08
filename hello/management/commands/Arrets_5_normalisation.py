import geopandas as gpd
from sklearn.preprocessing import MinMaxScaler

# Charger le fichier GeoJSON
file_path_input = "data/intermediate/chartreuse_scores.geojson"

gdf = gpd.read_file(file_path_input)

# Colonnes à normaliser
columns_to_normalize = [
    "duration_min_go",
    "duration_min_back",
    "elevation",
    "distance_to_pnr_border"
]

# Initialiser le scaler
scaler = MinMaxScaler()

# Appliquer la normalisation MinMax
normalized_values = scaler.fit_transform(gdf[columns_to_normalize])

# Ajouter les colonnes normalisées au GeoDataFrame
for i, col in enumerate(columns_to_normalize):
    new_col = f"{col}_normalized"
    gdf[new_col] = normalized_values[:, i]

# Sauvegarder en écrasant le fichier d'origine
file_path_output = "data/output/chartreuse_scores_final.geojson"

gdf.to_file(file_path_output, driver="GeoJSON")

print("✅ Fichier mis à jour avec colonnes normalisées.")
