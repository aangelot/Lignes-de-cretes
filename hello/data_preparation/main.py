# main.py
import geopandas as gpd
import subprocess
import sys
from pathlib import Path
import json
from utils import slugify
import os

# ---------- Helpers ----------
def choisir_massif():
    gdf_parks = gpd.read_file("data/input/massifs.geojson")
    massifs = sorted(gdf_parks["DRGP_L_LIB"].fillna(gdf_parks["nom_site"]).unique())
    print("Massifs disponibles :")
    for i, massif in enumerate(massifs, start=1):
        print(f"{i}. {massif}")
    choice = input("Sélectionnez un massif (numéro ou nom) : ").strip()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(massifs):
            return massifs[idx]
    elif choice in massifs:
        return choice
    print("❌ Sélection invalide")
    sys.exit(1)

def read_bbox_from_coord_max(massif):
    """Lit la bbox (lat_min, lng_min, lat_max, lng_max) depuis data/input/massifs_coord_max_with_centers.geojson."""
    path = "data/input/massifs_coord_max_with_centers.geojson"
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        nom = props.get("nom_pnr", "") or props.get("DRGP_L_LIB", "")
        if massif.lower() in nom.lower():
            # Certaines versions du GeoJSON ont ces noms de propriété
            lat_min = props.get("sud_lat_min") or props.get("south") or props.get("lat_min")
            lng_min = props.get("ouest_lng_min") or props.get("west") or props.get("lng_min")
            lat_max = props.get("nord_lat_max") or props.get("north") or props.get("lat_max")
            lng_max = props.get("est_lng_max") or props.get("east") or props.get("lng_max")
            if None in (lat_min, lng_min, lat_max, lng_max):
                return None
            return (float(lat_min), float(lng_min), float(lat_max), float(lng_max))
    return None

def estimate_poi_grid_count(bbox, pas_lat=0.005, pas_lng=0.005):
    if bbox is None:
        return None
    lat_min, lng_min, lat_max, lng_max = bbox
    # calcul approximatif du nombre de points dans la grille
    n_lat = int(((lat_max - lat_min) / pas_lat)) + 1
    n_lng = int(((lng_max - lng_min) / pas_lng)) + 1
    return max(0, n_lat * n_lng)

# ---------- Pipelines ----------
def pipeline_arrets(massif_name, script_dir, start_step=0):
    """Pipeline arrêts : étapes 0..5 (Arrets_0 -> Arrets_5)."""
    slug_massif = slugify(massif_name)

    steps = [
        ("Arrets_0_filtre.py", [massif_name]),
        ("Arrets_1_hubs_entree.py", [massif_name]),
        ("Arrets_2_calcul_aller.py", [massif_name]),
        ("Arrets_3_calcul_altitude.py", [massif_name]),
        ("Arrets_4_calcul_distance.py", [massif_name]),
        ("Arrets_5_normalisation.py", [massif_name]),
    ]

    for i, (script_name, args) in enumerate(steps):
        if i < start_step:
            print(f"⤷ Skip étape {i} ({script_name})")
            continue

        script_path = script_dir / script_name

        # confirmations spécifiques
        if script_name == "Arrets_1_hubs_entree.py":
            confirm = input(f"Avez-vous bien préparé le fichier data/output/{slug_massif}_hubs_entree.geojson ? [y/N] : ")
            if confirm != "y":
                print("❌ Étape Arrets_1 annulée par l’utilisateur.")
                return
        if script_name == "Arrets_2_calcul_aller.py":
            inter0_path = f"data/intermediate/{slug_massif}_arrets.geojson"
            if not os.path.exists(inter0_path):
                print(f"❌ Fichier introuvable : {inter0_path}")
                return
            gdf_inter0 = gpd.read_file(inter0_path)
            nb_appels_1 = len(gdf_inter0)
            confirm = input(f"\n⚠️ {nb_appels_1} requêtes vont être envoyées à l’API Google (Arrets_1). Continuer ? [y/N] : ").strip().lower()
            if confirm != "y":
                print("❌ Étape Arrets_1 annulée par l’utilisateur.")
                return

        print(f"\n▶️ Lancement {script_name} ...")
        try:
            subprocess.run([sys.executable, str(script_path), *args], check=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ Échec de {script_name} (exit {e.returncode})")
            raise

def pipeline_poi(massif_name, script_dir, start_step=0):
    """Pipeline POI : étapes 0..3 (POI_0_googlemaps, POI_1_OSM, POI_2_fusion, POI_3_scores)."""
    steps = [
        ("POI_0_googlemaps.py", [massif_name]),
        ("POI_1_OSM.py", [massif_name]),
        ("POI_2_fusion.py", [massif_name]),
        ("POI_3_scores.py", [massif_name]),
    ]

    for i, (script_name, args) in enumerate(steps):
        if i < start_step:
            print(f"⤷ Skip étape {i} ({script_name})")
            continue
        script_path = script_dir / script_name
        print(f"\n▶️ Lancement {script_name} ...")
        try:
            subprocess.run([sys.executable, str(script_path), *args], check=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ Échec de {script_name} (exit {e.returncode})")
            raise

def pipeline_graphe(massif_name, script_dir, start_step=0):
    """Pipeline graphe : étapes 0..2 (Graphe_0, Graphe_1_POI_fusion, Graphe_2_fichiers_finaux)."""
    steps = [
        ("Graphe_0.py", [massif_name]),
        ("Graphe_1_POI_fusion.py", [massif_name]),
        ("Graphe_2_fichiers_finaux.py", [massif_name]),
    ]

    for i, (script_name, args) in enumerate(steps):
        if i < start_step:
            print(f"⤷ Skip étape {i} ({script_name})")
            continue
        script_path = script_dir / script_name
        print(f"\n▶️ Lancement {script_name} ...")
        try:
            subprocess.run([sys.executable, str(script_path), *args], check=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ Échec de {script_name} (exit {e.returncode})")
            raise

# ---------- Main interactive ----------
def main():
    massif_name = choisir_massif()
    print(f"\n👉 Massif sélectionné : {massif_name}")

    script_dir = Path(__file__).parent.resolve()

    print("\nQue souhaitez-vous calculer ?")
    print("1. Arrêts uniquement")
    print("2. POI uniquement")
    print("3. Paths / Graphe uniquement")
    print("4. Tout (Arrêts + POI + Graphe)")

    choice = input("Votre choix : ").strip()

    # demander étape de départ selon le choix
    if choice == "1":
        print("\nÉtapes pipeline Arrêts (numéro) :")
        print("0. Arrets_0_filtre.py")
        print("1. Arrets_1_hubs_entree.py")
        print("2. Arrets_2_calcul_aller.py")
        print("3. Arrets_3_calcul_altitude.py")
        print("4. Arrets_4_calcul_distance.py")
        print("5. Arrets_5_normalisation.py")
        start_input = input("À partir de quelle étape voulez-vous reprendre ? (numéro, défaut=0) : ").strip()
        start_step = int(start_input) if start_input.isdigit() else 0
        pipeline_arrets(massif_name, script_dir, start_step=start_step)

    elif choice == "2":
        print("\nÉtapes pipeline POI (numéro) :")
        print("0. POI_0_googlemaps.py")
        print("1. POI_1_OSM.py")
        print("2. POI_2_fusion.py")
        print("3. POI_3_scores.py")
        start_input = input("À partir de quelle étape voulez-vous reprendre ? (numéro, défaut=0) : ").strip()
        start_step = int(start_input) if start_input.isdigit() else 0
        pipeline_poi(massif_name, script_dir, start_step=start_step)

    elif choice == "3":
        print("\nÉtapes pipeline Graphe (numéro) :")
        print("0. Graphe_0.py")
        print("1. Graphe_1_POI_fusion.py")
        print("2. Graphe_2_fichiers_finaux.py")
        start_input = input("À partir de quelle étape voulez-vous reprendre ? (numéro, défaut=0) : ").strip()
        start_step = int(start_input) if start_input.isdigit() else 0
        pipeline_graphe(massif_name, script_dir, start_step=start_step)

    elif choice == "4":
        # pour "Tout" on demande étape de départ pour chaque sous-pipeline
        print("\n--- Pipeline 'Tout' : pour chaque bloc choisissez l'étape de départ ---")
        print("\n[Arrêts] étapes 0..5 (défaut 0)")
        start_input = input("Arrêts : étape de départ (numéro, défaut=0) : ").strip()
        start_arrets = int(start_input) if start_input.isdigit() else 0

        print("\n[POI] étapes 0..3 (défaut 0)")
        start_input = input("POI : étape de départ (numéro, défaut=0) : ").strip()
        start_poi = int(start_input) if start_input.isdigit() else 0

        print("\n[Graphe] étapes 0..2 (défaut 0)")
        start_input = input("Graphe : étape de départ (numéro, défaut=0) : ").strip()
        start_graphe = int(start_input) if start_input.isdigit() else 0

        pipeline_arrets(massif_name, script_dir, start_step=start_arrets)
        pipeline_poi(massif_name, script_dir, start_step=start_poi)
        pipeline_graphe(massif_name, script_dir, start_step=start_graphe)

    else:
        print("❌ Choix invalide")

if __name__ == "__main__":
    main()
