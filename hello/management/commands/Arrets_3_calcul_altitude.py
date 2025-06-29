import geopandas as gpd
import requests
import time

# Charger le fichier GeoJSON
gdf = gpd.read_file("data/intermediate/chartreuse_scores.geojson")

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

# Ajouter la colonne et enregistrer
gdf["elevation"] = elevations
gdf.to_file("data/intermediate/chartreuse_scores.geojson", driver="GeoJSON")

print("✅ Altitudes ajoutées au fichier.")
