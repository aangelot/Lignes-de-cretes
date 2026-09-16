"""
Gestion des altitudes et des élévations.
Récupération, lissage et calcul de dénivelés.
"""

import logging
import time
import requests

from ..utils.geotools import haversine

logger = logging.getLogger(__name__)

ELEVATION_ATTR = "ele"

# Fenêtre de lissage, en mètres parcourus. L'espacement des nœuds varie de 10 m à
# 1 km selon les tronçons : une fenêtre exprimée en nombre de points lisserait
# 100 m ici et 9 km là.
SMOOTHING_WINDOW_M = 50

# Amplitude minimale d'une montée pour être comptée, en mètres. Filtre les
# oscillations résiduelles du modèle de terrain sans amputer les vraies montées.
ASCENT_THRESHOLD_M = 5

# En dessous de cette proportion de nœuds renseignés, l'interpolation des trous
# devient trop approximative : on repasse par l'API.
MIN_KNOWN_RATIO = 0.9


def _fill_gaps(elevations):
    """
    Comble les trous (None) d'une liste d'altitudes par interpolation linéaire.
    Les trous de début et de fin sont comblés par la première/dernière valeur connue.
    Suppose qu'au moins une valeur est connue.
    """
    known = [i for i, e in enumerate(elevations) if e is not None]
    filled = list(elevations)

    for i in range(0, known[0]):
        filled[i] = elevations[known[0]]
    for i in range(known[-1] + 1, len(filled)):
        filled[i] = elevations[known[-1]]

    for start, end in zip(known, known[1:]):
        if end == start + 1:
            continue
        span = end - start
        delta = elevations[end] - elevations[start]
        for i in range(start + 1, end):
            filled[i] = elevations[start] + delta * (i - start) / span

    return filled


def _elevations_from_graph(path, G):
    """
    Lit les altitudes précalculées sur les nœuds du graphe (cf. Graphe_3_altitudes.py).
    Retourne une liste de la longueur de `path`, ou None si le graphe ne permet pas
    de répondre (altitudes absentes ou trop lacunaires).
    """
    raw = []
    for node in path:
        key = tuple(node) if isinstance(node, list) else node
        try:
            raw.append(G.nodes[key].get(ELEVATION_ATTR))
        except (KeyError, TypeError):
            raw.append(None)

    known = sum(1 for e in raw if e is not None)
    if known == 0:
        logger.warning("Aucune altitude précalculée dans le graphe, repli sur l'API")
        return None

    ratio = known / len(raw)
    if ratio < MIN_KNOWN_RATIO:
        logger.warning(
            f"Seulement {known}/{len(raw)} altitudes précalculées ({ratio:.0%}), repli sur l'API"
        )
        return None

    if known < len(raw):
        logger.info(f"{len(raw) - known} altitudes manquantes sur {len(raw)}, comblées par interpolation")
        raw = _fill_gaps(raw)

    logger.info(f"Retrieved {len(raw)} elevations from graph")
    return raw


def _elevations_from_api(path):
    """
    Récupère les altitudes depuis l'API Open-Elevation.

    Essaie jusqu'à 3 fois en cas d'erreur ou de réponse vide.
    Si aucune tentative ne donne de résultat utilisable (ou que l'API renvoie
    un objet nul), on renvoie une liste de zéros.
    """
    url = "https://api.open-elevation.com/api/v1/lookup"

    locations = [{"latitude": lat, "longitude": lon} for lon, lat in path]
    all_elevations = []

    for attempt in range(1, 4):
        try:
            logger.debug(f"Attempt {attempt}/3 for {len(path)} elevation points")
            response = requests.post(url, json={"locations": locations}, timeout=60)
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


def get_elevations(path, G=None):
    """
    Retourne les altitudes des points d'un tracé.
    path : liste de tuples (lon, lat)
    G : graphe du massif, dont les nœuds portent l'altitude précalculée.

    Les points d'un tracé sont toujours des nœuds du graphe : les altitudes sont
    donc lues directement, sans appel réseau. On ne retombe sur l'API
    Open-Elevation que si le graphe n'est pas fourni ou n'a pas été enrichi
    (cf. hello/data_preparation/Graphe_3_altitudes.py).
    """
    if not path:
        return []

    if G is not None:
        elevations = _elevations_from_graph(path, G)
        if elevations is not None:
            return elevations

    return _elevations_from_api(path)


def _cumulative_distances(path):
    """Distances cumulées (m) le long du tracé, une valeur par point."""
    cumulative = [0.0]
    for (lon1, lat1), (lon2, lat2) in zip(path, path[1:]):
        cumulative.append(cumulative[-1] + haversine((lat1, lon1), (lat2, lon2)))
    return cumulative


def _smooth_by_index(elevations, window):
    """Moyenne mobile sur un nombre fixe de points (repli sans tracé)."""
    smoothed = []
    n = len(elevations)
    half_window = window // 2
    for i in range(n):
        start = max(0, i - half_window)
        end = min(n, i + half_window + 1)
        smoothed.append(sum(elevations[start:end]) / (end - start))
    return smoothed


def smooth_elevations(elevations, path=None, window_m=SMOOTHING_WINDOW_M):
    """
    Lisse les altitudes par moyenne mobile sur une fenêtre exprimée en mètres parcourus.
    path : coordonnées (lon, lat) des points, pour mesurer la fenêtre en distance.
           Sans tracé, on retombe sur une fenêtre de 9 points.
    """
    n = len(elevations)
    if n == 0:
        return []
    if path is None or len(path) != n:
        return _smooth_by_index(elevations, window=9)

    cumulative = _cumulative_distances(path)
    half_window = window_m / 2

    # Sommes préfixes : la moyenne sur une fenêtre se calcule alors en temps constant
    prefix = [0.0]
    for e in elevations:
        prefix.append(prefix[-1] + e)

    smoothed = []
    start = end = 0
    for i in range(n):
        while cumulative[i] - cumulative[start] > half_window:
            start += 1
        while end + 1 < n and cumulative[end + 1] - cumulative[i] <= half_window:
            end += 1
        smoothed.append((prefix[end + 1] - prefix[start]) / (end + 1 - start))

    return smoothed


def compute_total_ascent(elevations, threshold_m=ASCENT_THRESHOLD_M):
    """
    Calcule le dénivelé positif total par accumulation à hystérésis : chaque montée
    est comptée intégralement, mais seules celles dont l'amplitude dépasse
    `threshold_m` sont retenues.

    Un seuil appliqué à l'écart entre deux points consécutifs ne conviendrait pas :
    avec un espacement de l'ordre de 10 m, une pente de 15 % ne produit que 1,6 m
    d'écart par point et serait entièrement écartée.
    """
    if len(elevations) < 2:
        return 0

    total_ascent = 0.0
    low = high = elevations[0]
    climbing = False

    for elevation in elevations[1:]:
        if climbing:
            if elevation > high:
                high = elevation
            elif high - elevation > threshold_m:
                # Descente confirmée : la montée qui précède est acquise
                total_ascent += high - low
                climbing = False
                low = elevation
        else:
            if elevation < low:
                low = elevation
            elif elevation - low > threshold_m:
                climbing = True
                high = elevation

    if climbing:
        total_ascent += high - low

    return round(total_ascent)
