import json
import os
from dotenv import load_dotenv
import requests
import time
import sys

def get_duration_from_api(origin_coords, destination_coords):
    """Call Google Maps API to get duration in minutes"""
    load_dotenv()
    API_KEY = os.getenv("GOOGLE_API_KEY")
    origin = {"latitude": origin_coords[1], "longitude": origin_coords[0]}
    destination = {"latitude": destination_coords[1], "longitude": destination_coords[0]}

    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": "routes.duration"
    }
    body = {
        "origin": {"location": {"latLng": origin}},
        "destination": {"location": {"latLng": destination}},
        "travelMode": "TRANSIT",
        "transitPreferences": {
            "routingPreference": "FEWER_TRANSFERS"
        }
    }
    response = requests.post(url, headers=headers, json=body)
    if response.status_code == 200:
        try:
            duration_str = response.json()["routes"][0]["duration"]
            if "s" in duration_str:
                return int(int(duration_str.replace("s", "")) / 60)
            elif duration_str.startswith("PT"):
                h, m = 0, 0
                if "H" in duration_str:
                    h = int(duration_str.split("PT")[1].split("H")[0])
                    m_part = duration_str.split("H")[1]
                    if "M" in m_part:
                        m = int(m_part.split("M")[0])
                elif "M" in duration_str:
                    m = int(duration_str.split("PT")[1].split("M")[0])
                return h * 60 + m
        except Exception as e:
            print(f"Erreur d’analyse JSON: {e}")
            return 10000
    else:
        print(f"Erreur API {response.status_code}: {response.text}")
        return 10000

def ajouter_durations_hubs(massif):
    with open('data/input/hubs_departs.geojson', 'r') as f:
        hubs_departs = json.load(f)
    
    with open(f'data/output/{massif}_hubs_entree.geojson', 'r') as f:
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
            # Appel Google Maps API
            if entree_coords == depart_coords:
                duration = 0
            else:
                duration = get_duration_from_api(depart_coords, entree_coords)
            durations_from_hubs[hub_name] = duration
            print(f"Durée de {hub_name} à entrée {feature['properties']['id']}: {duration} min")
            time.sleep(0.1)  
        
        feature['properties']['durations_from_hubs'] = durations_from_hubs
    
    # Save updated geojson
    with open(f'data/output/{massif}_hubs_entree.geojson', 'w') as f:
        json.dump(hubs_entree, f, indent=2)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python Arrets_1_hubs_entree.py <Massif>")
        sys.exit(1)

    massif_name = sys.argv[1]
    ajouter_durations_hubs(massif_name)