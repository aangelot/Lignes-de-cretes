import geopandas as gpd
import pandas as pd
import unicodedata
import re
import json

# ---------- FONCTIONS UTILES ----------
def normalize_name(name):
    """Normalise les noms pour faciliter le matching : minuscules, accents, tirets/espaces."""
    if not isinstance(name, str):
        return ""
    # Minuscules
    name = name.lower()
    # Retirer accents
    name = ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    # Remplacer tirets et multiples espaces par un espace
    name = re.sub(r'[-_]', ' ', name)
    name = re.sub(r'\s+', ' ', name)
    # Supprimer espaces en début/fin
    name = name.strip()
    return name

# ---------- 1️⃣ Charger les données ----------
# CSV sans header
communes_csv = pd.read_csv("data/input/communes_zones_TCL.csv", header=None, names=["Commune", "CodePostal", "Zone"])

communes_a_exclure = [
    "bron", "caluire et cuire", "champagne au mont d'or", "chassieu", "corbas",
    "feyzin", "la mulatiere", "lyon", "mions", "rillieux la pape",
    "sainte foy les lyon", "saint fons", "saint priest",
    "venissieux", "villeurbanne"
]


# GeoJSON des communes de Rhône
gdf_communes = gpd.read_file("data/input/communes.json")
gdf_communes = gdf_communes[gdf_communes['dep'] == '69']



# Normalisation des noms pour matching + suppression communes trop urbaines
communes_csv['Commune_norm'] = communes_csv['Commune'].apply(normalize_name)
communes_csv = communes_csv[~communes_csv['Commune_norm'].isin(communes_a_exclure)]

gdf_communes['libgeo_norm'] = gdf_communes['libgeo'].apply(normalize_name)

# ---------- 2️⃣ Fusionner CSV et GeoJSON ----------
# Merge sur les noms normalisés
merged = gdf_communes.merge(communes_csv, left_on='libgeo_norm', right_on='Commune_norm', how='inner')
gdf = gpd.GeoDataFrame(merged, geometry='geometry', crs=gdf_communes.crs)

# ---------- 3️⃣ Fusionner toutes les zones en un seul polygone ----------
zone_unique = gdf.dissolve()  
zone_unique = zone_unique.reset_index(drop=True)

zone_unique['DRGP_C_COD'] = "FR8000058"
zone_unique['DRGP_L_LIB'] = "Lyonnais"

# ---------- 4️⃣ Exporter GeoJSON de la zone unique ----------
output_file = "data/output/zone_unique_Lyonnais.geojson"
zone_unique[['DRGP_C_COD', 'DRGP_L_LIB', 'geometry']].to_file(output_file, driver='GeoJSON')
print(f"✅ GeoJSON de la zone unique enregistré : {output_file}")

# ---------- 5️⃣ Ajouter cette feature dans PNR.geojson ----------
pnr_file = "data/input/PNR.geojson"

# Lire le PNR existant
with open(pnr_file, "r", encoding="utf-8") as f:
    pnr_data = json.load(f)

# Extraire la géométrie de notre zone unique (GeoJSON format)
zone_geojson_feature = json.loads(zone_unique[['DRGP_C_COD', 'DRGP_L_LIB', 'geometry']].to_json())['features'][0]

# Ajouter la feature au PNR
pnr_data['features'].append(zone_geojson_feature)

# Réécrire le PNR.geojson
with open(pnr_file, "w", encoding="utf-8") as f:
    json.dump(pnr_data, f, indent=2, ensure_ascii=False)

print(f"✅ Feature ajoutée à {pnr_file}")
