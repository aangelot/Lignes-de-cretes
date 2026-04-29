"""
Gestion des altitudes et des élévations.
Récupération, lissage et calcul de dénivelés.
"""

import logging
import time
import requests

logger = logging.getLogger(__name__)


def get_elevations(path, chunk_size=500):
    """
    Récupère les altitudes depuis l'API Open-Elevation.
    path : liste de tuples (lon, lat)
    chunk_size : nombre de points par requête (max 100 recommandé)

    Essaie jusqu'à 3 fois en cas d'erreur ou de réponse vide.
    Si aucune tentative ne donne de résultat utilisable (ou que l'API renvoie
    un objet nul), on renvoie une liste de zéros.
    """
    url = "https://api.open-elevation.com/api/v1/lookup"
    logger.info(f"Fetching elevations for {len(path)} points (chunk_size={chunk_size})")
    
    locations = [{"latitude": lat, "longitude": lon} for lon, lat in path]
    all_elevations = []

    for attempt in range(1, 4):
        try:
            logger.debug(f"Attempt {attempt}/3 for {len(path)} elevation points")
            response = requests.post(url, json={"locations": locations}, timeout=30)
            logger.debug(f"API response status: {response.status_code}")
            response.raise_for_status()

            full_response = response.json()
            results = full_response.get("results")

            if results and len(results) == len(path):
                all_elevations = [pt.get("elevation", 0) for pt in results]
                logger.debug(f"Got {len(all_elevations)} elevations")
                break
            else:
                logger.warning(
                    f"Elevation request returned unexpected result length: "
                    f"{len(results) if results is not None else 'None'} != {len(path)}"
                )
                raise ValueError("Résultat d'altitude invalide")

        except Exception as e:
            logger.error(f"Attempt {attempt}/3 failed: {type(e).__name__}: {e}")
            if attempt < 3:
                logger.info("Retrying in 1 second...")
                time.sleep(1)
                continue
            else:
                logger.warning("All 3 elevation attempts failed, using zeros")
                all_elevations = [0] * len(path)

    logger.info(f"Retrieved {len(all_elevations)} elevations total")
    return all_elevations


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
