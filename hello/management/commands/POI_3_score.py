import json
import os

# Charger les données GeoJSON
input_path = "data/intermediate/poi_fusionnes.geojson"
output_path = "data/intermediate/poi_scores.geojson"

with open(input_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

features = data['features']

# Extraire les élévations et ratings valides
elevations = []
ratings = []

for feat in features:
    props = feat['properties']
    elev = props.get('elevation')
    rating = props.get('rating')

    try:
        elev = float(elev)
        elevations.append(elev)
    except (ValueError, TypeError):
        pass

    try:
        rating = float(rating)
        ratings.append(rating)
    except (ValueError, TypeError):
        pass

# Normalisation linéaire
def normalize(val, min_val, max_val, target_min, target_max):
    if max_val == min_val:
        return target_min  # éviter division par zéro
    return target_min + (val - min_val) * (target_max - target_min) / (max_val - min_val)

min_elev, max_elev = min(elevations), max(elevations)
min_rating, max_rating = min(ratings), max(ratings)

# Ajouter le score à chaque feature
for feat in features:
    props = feat['properties']
    score = 0.3

    elev = props.get('elevation')
    rating = props.get('rating')

    if elev is not None:
        try:
            elev = float(elev)
            score = normalize(elev, min_elev, max_elev, 0.8, 1)
        except ValueError:
            pass

    else:
        if rating is not None:
            rating = float(rating)
            score = normalize(rating, min_rating, max_rating, 0, 1)
        else:
            score = 0.3

    props['score'] = round(score, 3)

# Écriture du fichier de sortie
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Fichier écrit : {output_path}")
