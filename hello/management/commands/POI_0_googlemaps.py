# POI_0_googlemaps.py
import os
import sys
import json
import requests
from dotenv import load_dotenv
from utils import slugify

# Charger la clé API depuis .env
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

def lire_bbox_pnr(fichier_geojson, nom_pnr_recherche):
    with open(fichier_geojson, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if props.get("nom_pnr") == nom_pnr_recherche:
            return (
                props.get("sud_lat_min"),
                props.get("ouest_lng_min"),
                props.get("nord_lat_max"),
                props.get("est_lng_max")
            )
    raise ValueError(f"PNR '{nom_pnr_recherche}' non trouvé dans {fichier_geojson}")


def generer_grille(bbox, pas_lat, pas_lng):
    lat_min, lng_min, lat_max, lng_max = bbox
    lat = lat_min
    points = []
    while lat <= lat_max:
        lng = lng_min
        while lng <= lng_max:
            points.append((lat, lng))
            lng += pas_lng
        lat += pas_lat
    return points


def fetch_pois(massif: str):
    fichier_geojson = "data/input/PNR_coord_max.geojson"
    bbox = lire_bbox_pnr(fichier_geojson, massif)

    pas_lat = 0.04
    pas_lng = 0.04
    grille_points = generer_grille(bbox, pas_lat, pas_lng)

    print(f"👉 {len(grille_points)} points générés pour la grille.")
    print("⚠️ Attention : chaque point déclenche une requête Google Maps API Nearby Search.")
    print("   Google facture au-delà de 1000 requêtes par mois.")
    confirm = input("Souhaitez-vous continuer ? (o/n) ").strip().lower()
    if confirm != "o":
        print("❌ Abandon de l’opération.")
        return

    features = []
    url = "https://places.googleapis.com/v1/places:searchNearby"

    for center_lat, center_lng in grille_points:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": API_KEY,
            "X-Goog-FieldMask": "*"
        }

        payload = {
            "includedTypes": [
                "hiking_area",
                "garden",
                "historical_landmark",
                "national_park",
            ],
            "maxResultCount": 20,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": center_lat, "longitude": center_lng},
                    "radius": 5000
                }
            }
        }

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        results = response.json().get("places", [])

        for place in results:
            location = place.get("location", {})
            lat = location.get("latitude")
            lng = location.get("longitude")

            if lat is not None and lng is not None:
                display_name = place.get("displayName", {}).get("text")
                primary_type = place.get("primaryType")
                maps_uri = place.get("googleMapsUri")
                rating = place.get("rating")

                feature = {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lng, lat]},
                    "properties": {
                        "title": display_name,
                        "primaryType": primary_type,
                        "googleMapsUri": maps_uri,
                        "rating": rating,
                    }
                }

                if not any(
                    f["geometry"]["coordinates"] == feature["geometry"]["coordinates"]
                    and f["properties"]["title"] == feature["properties"]["title"]
                    for f in features
                ):
                    features.append(feature)

    geojson = {"type": "FeatureCollection", "features": features}
    os.makedirs("data/intermediate", exist_ok=True)
    output_path = f"data/intermediate/{slugify(massif)}_poi_google_maps.geojson"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    print(f"✅ POI enregistrés dans {output_path} (total: {len(features)})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python POI_0_googlemaps.py <Massif>")
        sys.exit(1)

    massif_name = sys.argv[1]
    fetch_pois(massif_name)
