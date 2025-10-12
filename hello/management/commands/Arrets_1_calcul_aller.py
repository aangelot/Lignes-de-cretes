import sys
import geopandas as gpd
import requests
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import time
from shapely.geometry import Point
import json
from utils import slugify

def process_scores(massif: str, ville: str):
    # Charger la clé API depuis le fichier .env
    load_dotenv()
    API_KEY = os.getenv("GOOGLE_API_KEY")

    # Charger les coordonnées de la gare de départ depuis gares_departs.json
    with open("data/input/gares_departs.json", "r", encoding="utf-8") as f:
        gares = json.load(f)

    if ville not in gares:
        raise ValueError(f"Ville '{ville}' introuvable dans gares_departs.json")

    origin = gares[ville]

    # Charger les POI depuis le fichier GeoJSON (résultats de Arrets_0_filtre)
    arrets_path = f"data/intermediate/{slugify(massif)}_arrets.geojson"
    gdf = gpd.read_file(arrets_path)

    # Heure de départ : samedi prochain à 4h, en UTC
    now = datetime.now()
    days_ahead = (5 - now.weekday()) % 7  # 5 = samedi
    saturday = now + timedelta(days=days_ahead)
    departure_time = datetime.combine(
        saturday.date(), datetime.strptime("04:00", "%H:%M").time()
    )
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
        time.sleep(6)  # limiter les requêtes

    # Filtrer uniquement ceux avec une durée valide
    results = [r for r in results if r["duration_min_go"] is not None]
    output_gdf = gpd.GeoDataFrame(results, crs="EPSG:4326")

    # Exporter
    output_path = f"data/intermediate/{slugify(massif)}_{slugify(ville)}_arrets.geojson"
    output_gdf.to_file(output_path, driver="GeoJSON")
    print(f"✅ Fichier exporté : {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python Arrets_1_calcul_aller.py <Massif> <Ville>")
        sys.exit(1)

    massif_name = sys.argv[1]
    ville_name = sys.argv[2]
    process_scores(massif_name, ville_name)
