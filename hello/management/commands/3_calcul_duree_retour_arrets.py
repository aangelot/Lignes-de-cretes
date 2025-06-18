import geopandas as gpd
import requests
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import time

# Charger la clé API depuis le fichier .env
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

# Coordonnées de Lyon Part-Dieu
destination = {"latitude": 45.7601, "longitude": 4.8599}

# Charger les arrêts depuis le fichier existant
gdf = gpd.read_file("data/intermediate/2_chartreuse_scores.geojson")

# Heure de départ : dimanche prochain à 14h (UTC)
now = datetime.now()
days_ahead = (6 - now.weekday()) % 7  # 6 = dimanche
sunday = now + timedelta(days=days_ahead)
departure_time = datetime.combine(sunday.date(), datetime.strptime("14:00", "%H:%M").time())
departure_time_utc = departure_time.astimezone().isoformat()

# Fonction pour interroger l’API Google Directions
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
            # Conversion vers minutes
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

# Calculer la durée retour
durations_back = []
for idx, row in gdf.iterrows():
    lat, lon = row.geometry.y, row.geometry.x
    origin = {"latitude": lat, "longitude": lon}
    print(f"⏳ Retour depuis ({lat}, {lon})...")
    duration = get_transit_duration(origin, destination)
    durations_back.append(duration)
    time.sleep(0.1)  # limiter les requêtes

# Ajouter la colonne et filtrer
gdf["duration_min_back"] = durations_back
gdf = gdf[gdf["duration_min_back"].notnull()]

# Sauvegarder dans le même fichier
gdf.to_file("data/intermediate/2_chartreuse_scores.geojson", driver="GeoJSON")
print("✅ Fichier mis à jour : data/intermediate/2_chartreuse_scores.geojson")
