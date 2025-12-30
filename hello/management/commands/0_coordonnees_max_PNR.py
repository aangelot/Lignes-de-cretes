import json
import os

# Charger le fichier contenant tous les PNR
with open("data/input/massifs.geojson", "r", encoding="utf-8") as f:
    geojson = json.load(f)

features_output = []

for feature in geojson["features"]:
    name = feature["properties"].get("DRGP_L_LIB") or feature["properties"].get("nom_site", "Inconnu")
    geometry = feature["geometry"]

    # Gestion des différents types de géométrie (Polygon ou MultiPolygon)
    if geometry["type"] == "Polygon":
        rings = geometry["coordinates"]
    elif geometry["type"] == "MultiPolygon":
        rings = [ring for polygon in geometry["coordinates"] for ring in polygon]
    else:
        continue  # géométrie non prise en charge

    # Aplatir les points
    all_points = [pt for ring in rings for pt in ring]

    # Calcul des coordonnées extrêmes
    lats = [pt[1] for pt in all_points]
    lngs = [pt[0] for pt in all_points]

    min_lat = min(lats)
    max_lat = max(lats)
    min_lng = min(lngs)
    max_lng = max(lngs)

    center_lat = (min_lat + max_lat) / 2
    center_lng = (min_lng + max_lng) / 2

    # Construire la feature de sortie
    features_output.append({
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [center_lng, center_lat]
        },
        "properties": {
            "nom_pnr": name,
            "nord_lat_max": max_lat,
            "sud_lat_min": min_lat,
            "est_lng_max": max_lng,
            "ouest_lng_min": min_lng
        }
    })

# Construire le GeoJSON final
output_geojson = {
    "type": "FeatureCollection",
    "features": features_output
}

# Sauvegarder dans le dossier data/input/
os.makedirs("data/input", exist_ok=True)
with open("data/input/massifs_coord_max.geojson", "w", encoding="utf-8") as f:
    json.dump(output_geojson, f, ensure_ascii=False, indent=2)

print("✅ Coordonnées extrêmes enregistrées dans data/input/massifs_coord_max.geojson")