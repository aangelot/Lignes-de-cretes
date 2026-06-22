import requests
import json
import os
import sys
from utils import slugify

def fetch_osm_peaks(massif: str):
    # Charger les coordonnées bbox depuis le fichier GeoJSON
    with open("data/input/massifs_coord_max_with_centers.geojson", "r", encoding="utf-8") as f:
        pnr_data = json.load(f)

    bbox = None
    for feature in pnr_data["features"]:
        nom = feature["properties"].get("nom_pnr", "").lower()
        if massif.lower() in nom:
            bbox = {
                "south": feature["properties"]["sud_lat_min"],
                "north": feature["properties"]["nord_lat_max"],
                "west": feature["properties"]["ouest_lng_min"],
                "east": feature["properties"]["est_lng_max"]
            }
            break

    if bbox is None:
        raise ValueError(f"❌ Aucune entrée trouvée pour le PNR '{massif}' dans massifs_coord_max_with_centers.geojson")

    # Requête Overpass
    overpass_urls = [
        "https://overpass.kumi.systems/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass-api.de/api/interpreter",
    ]
    headers = {
        "User-Agent": "Lignes-de-cretes/1.0 (+https://github.com/)",
        "Accept": "application/json",
    }
    query = f"""
    [out:json][timeout:180];
    (
      node["natural"="peak"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
    );
    out body;
    """

    response = None
    for url in overpass_urls:
        try:
            print(f"🔎 Envoi de la requête Overpass vers {url}")
            response = requests.post(url, data=query, headers=headers, timeout=180)
            if response.status_code == 200:
                break
            print(f"  ⚠️ Serveur Overpass {url} a répondu {response.status_code}")
        except requests.RequestException as e:
            print(f"  ⚠️ Échec de connexion à {url} : {e}")

    if response is None or response.status_code != 200:
        raise RuntimeError("Aucun serveur Overpass n'a répondu correctement. Vérifiez votre connexion ou essayez un autre miroir.")

    try:
        data = response.json()
    except json.JSONDecodeError as e:
        raise ValueError(f"Réponse Overpass invalide : {e}\n{response.text[:500]}")

    # Transformation en GeoJSON
    features = []
    for element in data.get("elements", []):
        lat = element["lat"]
        lon = element["lon"]
        name = element.get("tags", {}).get("name")
        elevation = element.get("tags", {}).get("ele")

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "name": name,
                "elevation": elevation,
                "osm_id": element["id"]
            }
        })

    geojson = {"type": "FeatureCollection", "features": features}

    os.makedirs("data/intermediate", exist_ok=True)
    output_path = f"data/intermediate/{slugify(massif)}_sommets_osm.geojson"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    print(f"✅ {len(features)} sommets enregistrés dans {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python POI_1_OSM.py <Massif>")
        sys.exit(1)

    massif_name = sys.argv[1]
    fetch_osm_peaks(massif_name)
