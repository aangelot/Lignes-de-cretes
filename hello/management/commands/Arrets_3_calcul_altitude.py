import geopandas as gpd
import requests
import time
import sys
from utils import slugify

def add_elevations(massif: str):
    # Fichier d'entrée et de sortie
    file_path = f"data/intermediate/{slugify(massif)}_arrets.geojson"
    gdf = gpd.read_file(file_path)

    # Fonction pour récupérer l'altitude via l’API Open-Elevation
    def get_elevation(lat, lon):
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                return response.json()["results"][0]["elevation"]
        except:
            pass
        return None

    # Calculer les altitudes
    elevations = []
    for idx, row in gdf.iterrows():
        lat, lon = row.geometry.y, row.geometry.x
        print(f"📍 ({lat:.5f}, {lon:.5f}) — récupération de l'altitude...")
        elevation = get_elevation(lat, lon)
        elevations.append(elevation)
        time.sleep(0.1)  # limite pour éviter d’être bloqué

    # Ajouter la colonne et réécrire le fichier
    gdf["elevation"] = elevations
    gdf.to_file(file_path, driver="GeoJSON")
    print(f"✅ Altitudes ajoutées au fichier : {file_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python Arrets_3_altitude.py <Massif> ")
        sys.exit(1)

    massif_name = sys.argv[1]
    add_elevations(massif_name)
