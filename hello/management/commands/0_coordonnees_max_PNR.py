import json
import os
import math


def haversine(lat1, lon1, lat2, lon2):
    """
    Distance haversine en kilomètres.
    """
    R = 6371.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# Charger le fichier contenant tous les PNR
with open("data/input/massifs.geojson", "r", encoding="utf-8") as f:
    geojson = json.load(f)

features_output = []

for feature in geojson["features"]:
    name = feature["properties"].get("DRGP_L_LIB") or feature["properties"].get("nom_site", "Inconnu")
    geometry = feature["geometry"]

    # Gestion Polygon / MultiPolygon
    if geometry["type"] == "Polygon":
        rings = geometry["coordinates"]
    elif geometry["type"] == "MultiPolygon":
        rings = [ring for polygon in geometry["coordinates"] for ring in polygon]
    else:
        continue

    # Aplatir les points
    all_points = [pt for ring in rings for pt in ring]

    # Coordonnées extrêmes
    lats = [pt[1] for pt in all_points]
    lngs = [pt[0] for pt in all_points]

    min_lat = min(lats)
    max_lat = max(lats)
    min_lng = min(lngs)
    max_lng = max(lngs)

    center_lat = (min_lat + max_lat) / 2
    center_lng = (min_lng + max_lng) / 2

    # Diagonale bbox (sud-ouest -> nord-est)
    diagonal_km = haversine(min_lat, min_lng, max_lat, max_lng)

    # Feature sortie
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
            "ouest_lng_min": min_lng,
            "diagonal_km": round(diagonal_km, 1)
        }
    })

# GeoJSON final
output_geojson = {
    "type": "FeatureCollection",
    "features": features_output
}

# Sauvegarde
os.makedirs("data/input", exist_ok=True)
with open("data/input/massifs_coord_max.geojson", "w", encoding="utf-8") as f:
    json.dump(output_geojson, f, ensure_ascii=False, indent=2)

print("✅ Coordonnées extrêmes + diagonales enregistrées dans data/input/massifs_coord_max.geojson")