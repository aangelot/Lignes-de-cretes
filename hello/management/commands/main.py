# main.py
import geopandas as gpd
import subprocess
import sys
from pathlib import Path
import json
from utils import slugify

def main():
    # Charger les massifs depuis PNR.geojson
    gdf_parks = gpd.read_file("data/input/PNR.geojson")
    massifs = sorted(gdf_parks["DRGP_L_LIB"].unique())

    # Afficher la liste à l’utilisateur
    print("Massifs disponibles :")
    for i, massif in enumerate(massifs, start=1):
        print(f"{i}. {massif}")

    # Demander le choix du massif
    choice = input("Sélectionnez un massif (numéro ou nom) : ").strip()
    if choice.isdigit():
        idx = int(choice) - 1
        if idx < 0 or idx >= len(massifs):
            print("❌ Numéro invalide")
            return
        massif_name = massifs[idx]
    else:
        if choice not in massifs:
            print("❌ Nom invalide")
            return
        massif_name = choice

    print(f"👉 Traitement du massif : {massif_name}")

    # Construire le chemin absolu vers les scripts
    script_dir = Path(__file__).parent.resolve()
    arrets0_script = script_dir / "Arrets_0_filtre.py"
    arrets1_script = script_dir / "Arrets_1_calcul_aller.py"
    arrets2_script = script_dir / "Arrets_2_calcul_retour.py"
    arrets3_script = script_dir / "Arrets_3_calcul_altitude.py"
    arrets4_script = script_dir / "Arrets_4_calcul_distance.py"
    arrets5_script = script_dir / "Arrets_5_normalisation.py"

    # Étape 1 : Lancer Arrets_0_filtre.py
    subprocess.run([sys.executable, str(arrets0_script), massif_name], check=True)

    # Fichier intermédiaire après Arrets_0
    inter0_path = f"data/intermediate/{slugify(massif_name)}_arrets.geojson"

    # Lire le nombre d'entrées pour confirmation
    gdf_inter0 = gpd.read_file(inter0_path)
    nb_appels_1 = len(gdf_inter0)
    confirm1 = input(f"\n⚠️ {nb_appels_1} requêtes vont être envoyées à l’API Google (Arrets_1). Continuer ? [y/N] : ").strip().lower()
    if confirm1 != "y":
        print("❌ Étape Arrets_1 annulée par l’utilisateur.")
        sys.exit(0)

    # Étape 2 : Choix de la ville
    with open("data/input/gares_departs.json", "r", encoding="utf-8") as f:
        gares = json.load(f)

    villes = sorted(gares.keys())
    print("\nVilles de départ disponibles :")
    for i, ville in enumerate(villes, start=1):
        print(f"{i}. {ville}")

    choice_ville = input("Sélectionnez une ville (numéro ou nom) : ").strip()
    if choice_ville.isdigit():
        idx = int(choice_ville) - 1
        if idx < 0 or idx >= len(villes):
            print("❌ Numéro invalide")
            return
        ville_name = villes[idx]
    else:
        if choice_ville not in villes:
            print("❌ Nom invalide")
            return
        ville_name = choice_ville

    print(f"👉 Ville de départ : {ville_name}")

    # Étape 3 : Lancer Arrets_1_calcul_aller.py
    subprocess.run([sys.executable, str(arrets1_script), massif_name, ville_name], check=True)

    # Fichier intermédiaire commun pour Arrets_2
    inter_path = f"data/intermediate/{slugify(massif_name)}__{slugify(ville_name)}_arrets.geojson"

    # Étape 4 : Confirmation avant Arrets_2_calcul_retour.py
    gdf_inter = gpd.read_file(inter_path)
    nb_appels_2 = len(gdf_inter)
    confirm2 = input(f"\n⚠️ Lancer le calcul retour (Google API) ? {nb_appels_2} appels nécessaires [y/N] : ").strip().lower()
    if confirm2 == "y":
        subprocess.run([sys.executable, str(arrets2_script), massif_name, ville_name], check=True)
    else:
        print("⏭️ Étape Arrets_2_calcul_retour.py ignorée.")

    # Étape 5 : Lancer Arrets_3_calcul_altitude.py
    subprocess.run([sys.executable, str(arrets3_script), massif_name, ville_name], check=True)

    # Étape 6 : Lancer Arrets_4_calcul_distance.py
    subprocess.run([sys.executable, str(arrets4_script), massif_name, ville_name], check=True)

    # Étape 7 : Lancer Arrets_5_normalisation.py
    subprocess.run([sys.executable, str(arrets5_script), massif_name, ville_name], check=True)

if __name__ == "__main__":
    main()
