"""
Appels à l'API Google Maps Routes.
"""

import os
import requests
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_API_KEY")

_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def call_maps_routes_api(origin_latlon, destination_latlon, departure_time=None, arrival_time=None):
    """
    Appel à l'API Google Maps Routes v2 en mode TRANSIT.
    origin_latlon, destination_latlon : tuples (lat, lon)
    """
    def _loc(latlon):
        return {"location": {"latLng": {"latitude": latlon[0], "longitude": latlon[1]}}}

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "*",
    }
    body = {
        "origin": _loc(origin_latlon),
        "destination": _loc(destination_latlon),
        "travelMode": "TRANSIT",
        "transitPreferences": {"routingPreference": "FEWER_TRANSFERS"},
    }
    if departure_time is not None:
        if departure_time.tzinfo is None:
            departure_time = departure_time.replace(tzinfo=ZoneInfo("Europe/Paris"))
        body["departureTime"] = departure_time.isoformat()
    if arrival_time is not None:
        if arrival_time.tzinfo is None:
            arrival_time = arrival_time.replace(tzinfo=ZoneInfo("Europe/Paris"))
        body["arrivalTime"] = arrival_time.isoformat()

    r = requests.post(_ROUTES_URL, headers=headers, json=body)
    r.raise_for_status()
    return r.json()
