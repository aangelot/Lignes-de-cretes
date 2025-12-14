# Arrets_2_calcul_retour.py
import sys
import geopandas as gpd
import requests
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import time
import random
from shapely.geometry import Point
from utils import slugify
import json

# --- Vérification des arguments ---
if len(sys.argv) < 3:
    print("Usage: python Arrets_2_calcul_retour.py <massif> <ville>")
    sys.exit(1)

massif, ville = sys.argv[1], sys.argv[2]

# --- Chargement API ---
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    print("❌ Clé API Google non trouvée dans .env")
    sys.exit(1)

# --- Charger la gare de départ depuis le JSON ---
with open("data/input/gares_departs.json", "r", encoding="utf-8") as f:
    gares = json.load(f)

if ville not in gares:
    print(f"❌ Ville {ville} non trouvée dans gares_departs.json")
    sys.exit(1)

destination = gares[ville]

# --- Charger les arrêts intermédiaires ---
input_path = f"data/intermediate/{slugify(massif)}_{slugify(ville)}_arrets.geojson"
gdf = gpd.read_file(input_path)

# --- Heure de départ retour : dimanche prochain à 14h ---
now = datetime.now()
days_ahead = (6 - now.weekday()) % 7  # 6 = dimanche
sunday = now + timedelta(days=days_ahead)
departure_time = datetime.combine(sunday.date(), datetime.strptime("14:00", "%H:%M").time())
departure_time_utc = departure_time.astimezone().isoformat()

# --- Fonction robuste pour appeler l'API Google Directions ---
def get_transit_duration(origin, destination, max_retries=5):
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

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, headers=headers, json=body, timeout=20)
            if response.status_code == 200:
                try:
                    duration_str = response.json()["routes"][0]["duration"]
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
                    print(f"⚠️ Erreur d’analyse JSON: {e}")
                    return None
            else:
                print(f"⚠️ Erreur API {response.status_code}: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Erreur réseau (tentative {attempt}/{max_retries}): {e}")
            sleep_time = 2 ** attempt + random.random()  # backoff exponentiel
            print(f"⏳ Pause {sleep_time:.1f}s avant nouvelle tentative...")
            time.sleep(sleep_time)
    print("❌ Échec après plusieurs tentatives")
    return None

# --- Calculer les durées retour ---
durations_back = []
for idx, row in gdf.iterrows():
    lat, lon = row.geometry.y, row.geometry.x
    origin = {"latitude": lat, "longitude": lon}
    print(f"⏳ Retour depuis ({lat}, {lon})...")

    duration = get_transit_duration(origin, destination)
    durations_back.append(duration)

    # Pause entre chaque requête pour limiter les appels
    time.sleep(0.1)

# --- Ajouter la colonne et filtrer les entrées valides ---
gdf["duration_min_back"] = durations_back
gdf = gdf[gdf["duration_min_back"].notnull()]

# --- Sauvegarde (même fichier que Arrets_1) ---
output_path = f"data/intermediate/{slugify(massif)}_{slugify(ville)}_arrets.geojson"
gdf.to_file(output_path, driver="GeoJSON")

print(f"✅ Fichier mis à jour : {output_path}")
