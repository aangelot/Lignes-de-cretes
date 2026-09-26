import json
import os
from dotenv import load_dotenv
import time
import sys
from utils import slugify, haversine_m, transit_duration_minutes_any_hour, DEPARTURE_HOURS

# Valeur écrite quand aucune durée n'a pu être obtenue (lue comme « inconnue »)
UNKNOWN_DURATION_MIN = 10000

# En deçà, deux hubs sont la même gare : Google ne renvoie aucun itinéraire en
# transport pour un trajet nul, la durée est 0.
SAME_PLACE_MAX_M = 1000


def get_duration_from_api(origin_coords, destination_coords, hours=DEPARTURE_HOURS):
    """Durée en minutes entre deux points [lon, lat], UNKNOWN_DURATION_MIN si inconnue."""
    load_dotenv()
    if haversine_m(*origin_coords[:2], *destination_coords[:2]) < SAME_PLACE_MAX_M:
        return 0
    duration = transit_duration_minutes_any_hour(
        {"latitude": origin_coords[1], "longitude": origin_coords[0]},
        {"latitude": destination_coords[1], "longitude": destination_coords[0]},
        os.getenv("GOOGLE_API_KEY"),
        hours,
    )
    return UNKNOWN_DURATION_MIN if duration is None else duration

def ajouter_durations_hubs(massif):

    slug_massif = slugify(massif) 
    with open('data/input/hubs_departs.geojson', 'r') as f:
        hubs_departs = json.load(f)
    
    with open(f'data/output/{slug_massif}_hubs_entree.geojson', 'r') as f:
        hubs_entree = json.load(f)
    
    # Pour chaque hub d'entrée
    for feature in hubs_entree['features']:
        durations_from_hubs = {}
        entree_coords = feature['geometry']['coordinates']
        
        # Pour chaque hub de départ
        for hub_depart in hubs_departs['features']:
            hub_name = hub_depart['properties']['nom']
            depart_coords = hub_depart['geometry']['coordinates']
            
            # Appel Google Maps API
            duration = get_duration_from_api(depart_coords, entree_coords)
            durations_from_hubs[hub_name] = duration
            print(f"Durée de {hub_name} à entrée {feature['properties']['id']}: {duration} min")
            time.sleep(0.1)  
        
        for hub_entree in hubs_entree['features']:
            hub_name = hub_entree['properties']['id']
            depart_coords = hub_entree['geometry']['coordinates']
            # Appel Google Maps API (0 si même gare, cf. SAME_PLACE_MAX_M)
            duration = get_duration_from_api(depart_coords, entree_coords)
            durations_from_hubs[hub_name] = duration
            print(f"Durée de {hub_name} à entrée {feature['properties']['id']}: {duration} min")
            time.sleep(0.1)  
        
        feature['properties']['durations_from_hubs'] = durations_from_hubs
    
    # Save updated geojson
    with open(f'data/output/{slug_massif}_hubs_entree.geojson', 'w') as f:
        json.dump(hubs_entree, f, indent=2)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python Arrets_1_hubs_entree.py <Massif>")
        sys.exit(1)

    massif_name = sys.argv[1]
    ajouter_durations_hubs(massif_name)