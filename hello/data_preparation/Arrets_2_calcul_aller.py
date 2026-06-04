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
import math
def process_scores(massif: str):
    # Charger la clé API depuis le fichier .env
    load_dotenv()
    API_KEY = os.getenv("GOOGLE_API_KEY")

    # Charger les coordonnées des hubs d'entrée du massif
    with open(f"data/output/{slugify(massif)}_hubs_entree.geojson", "r", encoding="utf-8") as f:
        hubs_entree = json.load(f)
    # Construire la liste de hubs à partir du GeoJSON chargé
    hubs = []
    for feat in hubs_entree.get("features", []):
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates") if geom else None
        if coords and len(coords) >= 2:
            lon_h, lat_h = coords[0], coords[1]
            hubs.append({"latitude": lat_h, "longitude": lon_h, "properties": feat.get("properties", {})})

    # Fonction de distance Haversine (mètres)
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * R * math.asin(math.sqrt(a))

    # Retourne le hub le plus proche d'une paire lat/lon
    def get_nearest_hub(lat, lon):
        if not hubs:
            return None
        best = None
        id_best = None
        best_d = float("inf")
        for h in hubs:
            d = haversine(lat, lon, h["latitude"], h["longitude"])
            if d < best_d:
                best_d = d
                best = h
                id_best = h["properties"].get("id")
        return {"latitude": best["latitude"], "longitude": best["longitude"]}, id_best if best else None

    # Charger les arrêts  depuis le fichier GeoJSON (résultats de Arrets_0_filtre)
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
        origin, id_origin = get_nearest_hub(lat, lon)
        print(f"Calcul du trajet vers ({lat}, {lon})...")
        duration_min = get_transit_duration(origin, destination)
        results.append({
            "duration": duration_min,
            "geometry": Point(lon, lat),
            "hubs_entree": id_origin
        })
        time.sleep(0.1)  # limiter les requêtes

    # Filtrer uniquement ceux avec une durée valide
    results = [r for r in results if r["duration"] is not None]
    output_gdf = gpd.GeoDataFrame(results, crs="EPSG:4326")

    # Exporter
    output_path = f"data/intermediate/{slugify(massif)}_arrets.geojson"
    output_gdf.to_file(output_path, driver="GeoJSON")
    print(f"✅ Fichier exporté : {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python Arrets_2_calcul_aller.py <Massif>")
        sys.exit(1)

    massif_name = sys.argv[1]
    process_scores(massif_name)
