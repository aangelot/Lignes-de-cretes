#!/usr/bin/env python3
"""
Script pour ajouter un attribut 'centre' à chaque massif dans massifs_coord_max.geojson
"""

import json
import os

def add_center_attribute_to_massifs():
    """
    Ajoute un attribut 'centre' à chaque feature du fichier massifs_coord_max.geojson
    """
    input_file = "data/input/massifs_coord_max.geojson"
    output_file = "data/input/massifs_coord_max_with_centers.geojson"

    # Vérifier que le fichier d'entrée existe
    if not os.path.exists(input_file):
        print(f"❌ Fichier {input_file} introuvable")
        return False

    # Charger le fichier GeoJSON
    with open(input_file, 'r', encoding='utf-8') as f:
        geojson_data = json.load(f)

    # Ajouter l'attribut 'centre' à chaque feature
    modified_count = 0
    for feature in geojson_data.get('features', []):
        if feature.get('geometry', {}).get('type') == 'Point':
            coordinates = feature['geometry']['coordinates']
            # Ajouter l'attribut centre dans les properties
            feature['properties']['centre'] = {
                'longitude': coordinates[0],
                'latitude': coordinates[1]
            }
            modified_count += 1
            print(f"✅ Ajouté centre pour {feature['properties'].get('nom_pnr', 'Massif inconnu')}: {coordinates}")

    # Sauvegarder le fichier modifié
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(geojson_data, f, indent=2, ensure_ascii=False)

    print(f"✅ Fichier modifié sauvegardé: {output_file}")
    print(f"✅ {modified_count} massifs traités")

    return True

if __name__ == "__main__":
    add_center_attribute_to_massifs()