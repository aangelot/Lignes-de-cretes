"""
Gestion des altitudes et des élévations.
Récupération, lissage et calcul de dénivelés.
"""

import requests


def get_elevations(path):
    """
    Récupère les altitudes depuis l'API Open-Elevation.
    path : liste de tuples (lon, lat)
    """
    locations = [{"latitude": lat, "longitude": lon} for lon, lat in path]
    url = "https://api.open-elevation.com/api/v1/lookup"
    response = requests.post(url, json={"locations": locations})
    response.raise_for_status()
    results = response.json()["results"]
    elevations = [pt["elevation"] for pt in results]
    return elevations


def smooth_elevations(elevations, window=3):
    """
    Lisse les altitudes avec une moyenne mobile.
    window : taille de la fenêtre de lissage (impair recommandé)
    """
    smoothed = []
    n = len(elevations)
    half_window = window // 2
    for i in range(n):
        start = max(0, i - half_window)
        end = min(n, i + half_window + 1)
        smoothed.append(sum(elevations[start:end]) / (end - start))
    return smoothed


def compute_total_ascent(elevations, min_diff=2):
    """
    Calcule le dénivelé positif total.
    min_diff : variation minimale à prendre en compte pour éviter le bruit
    """
    total_ascent = 0
    for i in range(1, len(elevations)):
        delta = elevations[i] - elevations[i-1]
        if delta > min_diff:
            total_ascent += delta
    return round(total_ascent)
