import os
import json
import requests
from dotenv import load_dotenv

# Charger la clé API depuis .env
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

def lire_bbox_pnr(fichier_geojson, nom_pnr_recherche):
    with open(fichier_geojson, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if props.get("nom_pnr") == nom_pnr_recherche:
            nord_lat_max = props.get("nord_lat_max")
            sud_lat_min = props.get("sud_lat_min")
            est_lng_max = props.get("est_lng_max")
            ouest_lng_min = props.get("ouest_lng_min")
            return (sud_lat_min, ouest_lng_min, nord_lat_max, est_lng_max)
    raise ValueError(f"PNR '{nom_pnr_recherche}' non trouvé dans {fichier_geojson}")

def generer_grille(bbox, pas_lat, pas_lng):
    """
    bbox = (lat_min, lng_min, lat_max, lng_max)
    """
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

fichier_geojson = "data/input/PNR_coord_max.geojson"
nom_pnr = "Chartreuse"  

try:
    bbox = lire_bbox_pnr(fichier_geojson, nom_pnr)
    print(f"Bbox {nom_pnr} extraite : {bbox}")
except ValueError as e:
    print(e)
    bbox = None

if bbox:
    pas_lat = 0.005  
    pas_lng = 0.005
    grille_points = generer_grille(bbox, pas_lat, pas_lng)
    print(f"{len(grille_points)} points générés pour la grille.")
    # Affiche les 5 premiers points pour contrôle
    for p in grille_points[:5]:
        print(p)

features = []

# Endpoint de l’API Nearby Search (New)
url = "https://places.googleapis.com/v1/places:searchNearby"

for center_lat, center_lng in grille_points:
    # Paramètres de requête
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
            "historical_place",
            "cultural_landmark",
            "monument",
            "museum"
        ],
        "maxResultCount": 20,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": center_lat,
                    "longitude": center_lng
                },
                "radius": 500
            }
        }
    }


    # Appel de l’API
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

            photo_url = None
            photos = place.get("photos", [])
            if photos and isinstance(photos, list):
                photo_name = photos[0].get("name")
                if photo_name:
                    photo_url = f"https://places.googleapis.com/v1/{photo_name}/media?maxHeightPx=400&key={API_KEY}"

            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lng, lat]
                },
                "properties": {
                    "title": display_name,
                    "primaryType": primary_type,
                    "googleMapsUri": maps_uri,
                    "rating": rating,
                    "photo": photo_url
                }
            }

            # Optionnel : éviter doublons simples (coordonnées + titre)
            if not any(f["geometry"]["coordinates"] == feature["geometry"]["coordinates"] and
                        f["properties"]["title"] == feature["properties"]["title"] for f in features):
                features.append(feature)

# Après avoir parcouru toute la grille, on écrit tout en une fois
geojson = {
    "type": "FeatureCollection",
    "features": features
}

os.makedirs("data/input", exist_ok=True)
output_path = "data/input/poi_googlemaps_chartreuse.geojson"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(geojson, f, ensure_ascii=False, indent=2)

print(f"✅ POI enregistrés dans {output_path} (total: {len(features)})")

