import geopandas as gpd
import requests
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import time
from shapely.geometry import Point

# Charger la clé API depuis le fichier .env
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

# Coords de Lyon Part-Dieu
origin = {"latitude": 45.7601, "longitude": 4.8599}

# Charger les POI depuis le fichier GeoJSON
gdf = gpd.read_file("data/intermediate/1_chartreuse_arrets.geojson")

# Heure de départ : samedi prochain à 4h, en UTC (nécessaire pour l’API)
now = datetime.now()
days_ahead = (5 - now.weekday()) % 7  # 5 = samedi
saturday = now + timedelta(days=days_ahead)
departure_time = datetime.combine(saturday.date(), datetime.strptime("04:00", "%H:%M").time())
departure_time_utc = departure_time.astimezone().isoformat()

# Fonction pour appeler l’API Google Directions
def get_transit_duration(origin, destination):
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": "routes.duration"
    }
    body = {
        "origin": {"location": {"latLng": origin}},
        "destination": {"location": {"latLng": destination}},
        "travelMode": "TRANSIT",
        "departureTime": departure_time_utc,
        "transitPreferences": {
            "routingPreference": "FEWER_TRANSFERS"
        }
    }
    response = requests.post(url, headers=headers, json=body)
    if response.status_code == 200:
        try:
            duration_str = response.json()["routes"][0]["duration"]
            # Convertir le format "1234s" ou "PT1H12M" vers minutes
            if "s" in duration_str:
                return int(int(duration_str.replace("s", "")) / 60)
            elif duration_str.startswith("PT"):
                h, m = 0, 0
                if "H" in duration_str:
                    h = int(duration_str.split("PT")[1].split("H")[0])
                    m_part = duration_str.split("H")[1]
                    if "M" in m_part:
                        m = int(m_part.split("M")[0])
                elif "M" in duration_str:
                    m = int(duration_str.split("PT")[1].split("M")[0])
                return h * 60 + m
        except Exception as e:
            print(f"Erreur d’analyse JSON: {e}")
            return None
    else:
        print(f"Erreur API {response.status_code}: {response.text}")
        return None

# Calculer la durée pour chaque POI
results = []
for idx, row in gdf.iterrows():
    lon, lat = row.geometry.x, row.geometry.y
    destination = {"latitude": lat, "longitude": lon}
    print(f"Calcul du trajet vers ({lat}, {lon})...")
    duration_min = get_transit_duration(origin, destination)
    results.append({
        "duration_min_go": duration_min,
        "geometry": Point(lon, lat)
    })
    time.sleep(0.1)  # pour éviter d’être bloqué par l’API

gdf = gdf[gdf['duration_min_go'].notnull()]
output_gdf = gpd.GeoDataFrame(results, crs="EPSG:4326")
output_gdf.to_file("data/intermediate/2_chartreuse_scores"
".geojson", driver="GeoJSON")

print("✅ Fichier exporté : data/intermediate/2_chartreuse_scores.geojson")
