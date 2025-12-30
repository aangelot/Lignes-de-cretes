import sys
from pathlib import Path
import geopandas as gpd
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
import overpy
from utils import slugify
import pandas as pd
import http.client
import networkx as nx

# Calcule un score "randonnabilité" pour chaque tronçon
def score_randonnabilite(attrs):
    hw = attrs.get("highway", "")
    foot = attrs.get("foot", None)
    sac = attrs.get("sac_scale", None)

    if hw in ["motorway", "trunk", "primary"]:
        return 0.1
    elif hw in ["secondary", "tertiary", "unclassified", "residential"]:
        return 0.2
    elif hw in ["track", "service"]:
        return 0.5
    elif hw in ["footway", "path"]:
        if foot in ["yes", "permissive", "designated"]:
            return 1.0
        return 0.9
    elif sac in ["hiking", "mountain_hiking"]:
        return 1.0

    return 0.2

# Convertit un polygone en bbox compatible Overpass
def polygon_to_bbox(poly: Polygon):
    minx, miny, maxx, maxy = poly.bounds
    return miny, minx, maxy, maxx

# Découpe une grande bbox en sous-bbox pour éviter les timeouts Overpass
def split_bbox(bbox, n=2):
    south, west, north, east = bbox
    lat_step = (north - south) / n
    lon_step = (east - west) / n

    boxes = []
    for i in range(n):
        for j in range(n):
            boxes.append((
                south + i * lat_step,
                west + j * lon_step,
                south + (i + 1) * lat_step,
                west + (j + 1) * lon_step
            ))

    return boxes

def main(massif_name: str):

    print(f"🔍 Chargement du massif '{massif_name}'…")

    # Lecture du fichier PNR
    gdf_parks = gpd.read_file("data/input/massifs.geojson")
    gdf_massif = gdf_parks[gdf_parks["DRGP_L_LIB"] == massif_name]

    if gdf_massif.empty:
        print(f"❌ Massif '{massif_name}' introuvable dans massifs.geojson")
        sys.exit(1)

    # Buffer 2 km autour du massif
    print("🗺️ Application du buffer 2 km…")
    gdf_massif = gdf_massif.to_crs(epsg=2154)
    gdf_buffered = gdf_massif.buffer(2000)
    gdf_buffered = gdf_buffered.to_crs(epsg=4326)

    # Union des géométries
    geometry_union = unary_union(gdf_buffered.geometry)

    # Génération de la bbox
    bbox = polygon_to_bbox(geometry_union)
    print(f"📦 BBOX principale : {bbox}")

    # Fractionnement pour limiter les plantages Overpass
    sub_bboxes = split_bbox(bbox, n=3)
    print(f"🧩 {len(sub_bboxes)} sous-bbox générées")

    # API Overpass
    api = overpy.Overpass(url="https://overpass-api.de/api/interpreter")
    all_rows = []

    # Boucle sur chaque sous-bbox
    for bbox in sub_bboxes:
        s, w, n, e = bbox
        print(f"📡 Interrogation Overpass pour {bbox}")

        query = f"""
        [out:json][timeout:600];
        (
          way["highway"]({s},{w},{n},{e});
        );
        out body;
        >;
        out skel qt;
        """

        # Retry automatique
        for attempt in range(5):
            try:
                print(f"  🔁 Tentative {attempt+1}/5…")
                result = api.query(query)
                print("  ✅ Succès")
                break
            except (overpy.exception.OverpassGatewayTimeout,
                    overpy.exception.OverpassTooManyRequests,
                    http.client.IncompleteRead) as e:
                print(f"  ⚠️ Erreur Overpass : {e}")
                import time
                print("  ⏳ Attente 5 secondes avant retry…")
                time.sleep(5)
        else:
            print("❌ Abandon pour cette bbox")
            continue

        # Extraction des ways
        for way in result.ways:
            try:
                coords = [(float(node.lon), float(node.lat)) for node in way.nodes]
                geom = LineString(coords)

                # Filtre géographique
                if not geom.intersects(geometry_union):
                    continue

                attrs = way.tags
                score = score_randonnabilite(attrs)
                all_rows.append({"geometry": geom, "randonnabilite_score": score})

            except Exception as e:
                print(f"⚠️ Erreur sur un way: {e}")

    if not all_rows:
        print("❌ Aucun chemin récupéré")
        sys.exit(1)

    print(f"📥 {len(all_rows)} tronçons récupérés avant filtrage…")

    # Création du GeoDataFrame
    gdf_edges = gpd.GeoDataFrame(all_rows, crs="EPSG:4326")

    # Construction d'un graphe non orienté
    print("🔗 Construction du graphe pour détecter les composantes connexes…")
    G = nx.Graph()

    for idx, row in gdf_edges.iterrows():
        coords = list(row.geometry.coords)
        for (x1, y1), (x2, y2) in zip(coords[:-1], coords[1:]):
            G.add_edge((x1, y1), (x2, y2), index=idx)

    # Composantes
    components = list(nx.connected_components(G))
    print(f"🧩 Composantes trouvées : {len(components)}")

    # Sélection du plus grand composant
    largest_comp = max(components, key=len)
    print(f"🏆 Plus grand composant : {len(largest_comp)} noeuds")

    # Filtrage des edges appartenant à ce composant
    edges_to_keep = set()
    for u, v, data in G.edges(data=True):
        if u in largest_comp and v in largest_comp:
            edges_to_keep.add(data["index"])

    print(f"📉 Conservation de {len(edges_to_keep)} tronçons après filtrage par composante principale")

    gdf_edges = gdf_edges.loc[list(edges_to_keep)].copy()
    gdf_edges.reset_index(drop=True, inplace=True)

    # Sauvegarde
    massif_slug = slugify(massif_name)
    output_path = Path("data/intermediate") / f"{massif_slug}_hiking_paths.geojson"

    print(f"💾 Sauvegarde dans {output_path}")
    gdf_edges.to_file(output_path, driver="GeoJSON")

    print("✔️ Terminé !")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Utilisation : python Graphe_0_overpy.py '<Nom du massif>'")
        sys.exit(1)

    massif_name = sys.argv[1]
    main(massif_name)
