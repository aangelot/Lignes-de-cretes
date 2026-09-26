import math
import re
import time
import unicodedata
from datetime import datetime, timedelta

import requests


def normalize_label(s: str) -> str:
    """Normalise un texte : déaccentuation, tirets en espaces, minuscules."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def slugify(name: str) -> str:
    """Transforme une chaîne en identifiant safe pour les fichiers"""
    cleaned = normalize_label(name)
    return re.sub(r'[^a-z0-9]+', '_', cleaned).strip("_")


def haversine_m(lon1, lat1, lon2, lat2):
    """Distance à vol d'oiseau en mètres entre deux points (lon, lat)."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def next_saturday_departure_iso(hour=4):
    """
    Départ de référence des durées précalculées : samedi prochain à `hour` h, heure
    locale. Toujours dans le futur : lancé un samedi, le calcul visait ce samedi-là
    à 4 h, souvent déjà passé, et Google ne renvoyait alors aucun itinéraire.
    """
    now = datetime.now()
    days_ahead = (5 - now.weekday()) % 7 or 7  # 5 = samedi
    saturday = now + timedelta(days=days_ahead)
    return datetime.combine(saturday.date(), datetime.min.time()).replace(hour=hour).astimezone().isoformat()


def _parse_duration_minutes(duration_str):
    if "s" in duration_str and not duration_str.startswith("PT"):
        return int(int(duration_str.replace("s", "")) / 60)
    h, m = 0, 0
    if "H" in duration_str:
        h = int(duration_str.split("PT")[1].split("H")[0])
        m_part = duration_str.split("H")[1]
        if "M" in m_part:
            m = int(m_part.split("M")[0])
    elif "M" in duration_str:
        m = int(duration_str.split("PT")[1].split("M")[0])
    return h * 60 + m


def transit_duration_minutes(origin, destination, api_key, departure_iso=None, attempts=3):
    """
    Durée d'un trajet en transport en commun (Google Routes), en minutes.

    origin, destination : {"latitude": ..., "longitude": ...}
    Retourne None si aucun itinéraire n'est obtenu après `attempts` essais : erreurs
    d'API et réponses vides sont le plus souvent passagères, on les relance.
    """
    body = {
        "origin": {"location": {"latLng": origin}},
        "destination": {"location": {"latLng": destination}},
        "travelMode": "TRANSIT",
        "departureTime": departure_iso or next_saturday_departure_iso(),
        "transitPreferences": {"routingPreference": "FEWER_TRANSFERS"},
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.duration",
    }
    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(
                "https://routes.googleapis.com/directions/v2:computeRoutes",
                headers=headers, json=body, timeout=30,
            )
            if response.status_code == 200:
                routes = response.json().get("routes") or []
                if routes:
                    return _parse_duration_minutes(routes[0]["duration"])
                reason = "aucun itinéraire"
            else:
                reason = f"erreur API {response.status_code}: {response.text[:200]}"
        except (requests.RequestException, ValueError, KeyError) as e:
            reason = f"{type(e).__name__}: {e}"
        print(f"⚠️ Essai {attempt}/{attempts} sans durée ({reason})")
        if attempt < attempts:
            time.sleep(2 * attempt)
    return None


# Heures de départ essayées tour à tour. Certains trajets n'ont aucun itinéraire
# à 4 h mais en ont plus tard dans la matinée (Clermont-Ferrand → Avallon à 7 h,
# Briançon → Sospel à 10 h).
DEPARTURE_HOURS = (4, 7, 10)


def transit_duration_minutes_any_hour(origin, destination, api_key, hours=DEPARTURE_HOURS):
    """Première durée obtenue en partant samedi prochain à l'une des heures `hours`."""
    for hour in hours:
        duration = transit_duration_minutes(
            origin, destination, api_key, next_saturday_departure_iso(hour)
        )
        if duration is not None:
            return duration
    return None
