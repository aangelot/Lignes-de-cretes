import geopandas as gpd
from sklearn.preprocessing import MinMaxScaler
import sys
from utils import slugify

def normalize_scores(massif: str, ville: str):
    # Fichier d'entrée
    file_path_input = f"data/intermediate/{slugify(massif)}_{slugify(ville)}_arrets.geojson"
    gdf = gpd.read_file(file_path_input)

    # Colonnes à normaliser
    columns_to_normalize = [
        "duration_min_go",
        "duration_min_back",
        "elevation",
        "distance_to_pnr_border"
    ]

    # Normalisation MinMax
    scaler = MinMaxScaler()
    normalized_values = scaler.fit_transform(gdf[columns_to_normalize])

    # Ajouter les colonnes normalisées
    for i, col in enumerate(columns_to_normalize):
        gdf[f"{col}_normalized"] = normalized_values[:, i]

    # Fichier de sortie
    file_path_output = f"data/output/{slugify(massif)}_{slugify(ville)}_final.geojson"
    gdf.to_file(file_path_output, driver="GeoJSON")

    print(f"✅ Fichier mis à jour avec colonnes normalisées : {file_path_output}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python Arrets_5_normalisation.py <Massif> <Ville>")
        sys.exit(1)

    massif_name = sys.argv[1]
    ville_name = sys.argv[2]
    normalize_scores(massif_name, ville_name)
