import json
import os
import sys
from utils import slugify


def normalize(val, min_val, max_val, target_min, target_max):
    if max_val == min_val:
        return target_min  # éviter division par zéro
    return target_min + (val - min_val) * (target_max - target_min) / (max_val - min_val)

def main(massif):
    massif = slugify(massif)
    input_path = f"data/intermediate/{massif}_poi_fusionnes.geojson"
    output_path = f"data/output/{massif}_poi_scores.geojson"

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    features = data['features']

    # Extraire élévations et ratings valides
    elevations, ratings = [], []
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

    min_elev, max_elev = (min(elevations), max(elevations)) if elevations else (0, 0)
    min_rating, max_rating = (min(ratings), max(ratings)) if ratings else (0, 0)

    # Attribution du score
    for feat in features:
        props = feat['properties']
        score = 0.3  # valeur par défaut

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
                try:
                    rating = float(rating)
                    score = normalize(rating, min_rating, max_rating, 0, 0.8)
                except ValueError:
                    score = 0.3
            else:
                score = 0.3

        # Bonus pour hiking_area
        if props.get("type") == "hiking_area":
            score = min(score + 0.1, 1.0)

        props['score'] = round(score, 3)

    # Sauvegarde
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ Fichier écrit : {output_path} (total: {len(features)} POI)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Usage: python POI_3_scores.py <massif>")
        sys.exit(1)
    massif = sys.argv[1]
    main(massif)
