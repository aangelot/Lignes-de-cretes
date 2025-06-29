import geopandas as gpd
from shapely.geometry import Point
import json
import pyproj

def calculate_minimum_enclosing_circle_meters(geometry):
    # Reprojeter en UTM (zone adaptée à la géométrie)
    centroid = geometry.centroid
    lon, lat = centroid.x, centroid.y
    utm_zone = int((lon + 180) / 6) + 1
    is_northern = lat >= 0

    # EPSG UTM zone selon hémisphère
    epsg_utm = 32600 + utm_zone if is_northern else 32700 + utm_zone

    # Transformer vers UTM
    gdf_local = gpd.GeoSeries([geometry], crs="EPSG:4326").to_crs(epsg=epsg_utm)
    geom_utm = gdf_local.iloc[0]

    # Cercle englobant min (approximation via enveloppe convexe)
    convex_hull = geom_utm.convex_hull
    center_utm = convex_hull.centroid
    coords = list(convex_hull.exterior.coords)
    radius_m = max(center_utm.distance(Point(c)) for c in coords)

    # Reprojeter le centre en WGS84 pour la sortie
    project_back = pyproj.Transformer.from_crs(epsg_utm, 4326, always_xy=True)
    center_lon, center_lat = project_back.transform(center_utm.x, center_utm.y)

    return (center_lon, center_lat), radius_m

# Chargement GeoJSON
gdf = gpd.read_file("data/input/PNR.geojson")

output_features = []

for idx, row in gdf.iterrows():
    nom_parc = row['DRGP_L_LIB']
    geom = row.geometry

    center, radius_m = calculate_minimum_enclosing_circle_meters(geom)

    feature = {
        "type": "Feature",
        "properties": {
            "nom_parc": nom_parc,
            "centre_cercle": list(center),
            "rayon_m": radius_m
        },
        "geometry": {
            "type": "Point",
            "coordinates": list(center)
        }
    }
    output_features.append(feature)

output_geojson = {
    "type": "FeatureCollection",
    "features": output_features
}

with open("data/input/PNR_centres_rayons.geojson", "w") as f:
    json.dump(output_geojson, f, indent=2)

print("Fichier 'PNR_centres_rayons.geojson' créé avec succès.")
