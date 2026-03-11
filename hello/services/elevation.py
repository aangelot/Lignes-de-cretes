"""
Gestion des altitudes et des élévations.
Récupération, lissage et calcul de dénivelés.
"""

import requests


def get_elevations(path):
    """
    Récupère les altitudes depuis l'API Open-Elevation.
    path : liste de tuples (lon, lat)

    Essaie jusqu'à 3 fois en cas d'erreur ou de réponse vide.
    Si aucune tentative ne donne de résultat utilisable (ou que l'API renvoie
    un objet nul), on renvoie une liste de zéros.
    """
    locations = [{"latitude": lat, "longitude": lon} for lon, lat in path]
    url = "https://api.open-elevation.com/api/v1/lookup"

    for attempt in range(1, 4):
        try:
            response = requests.post(url, json={"locations": locations}, timeout=10)
            response.raise_for_status()
            results = response.json().get("results")
            if results:
                elevations = [pt.get("elevation", 0) for pt in results]
                return elevations
            # réponse vide
            raise ValueError("Résultat d'altitude vide")
        except Exception as e:
            if attempt < 3:
                continue
            else:
                # renvoyer des zéros pour chaque point
                return [0] * len(path)
    return [0] * len(path)


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
    ascent = round(total_ascent)
    return ascent
