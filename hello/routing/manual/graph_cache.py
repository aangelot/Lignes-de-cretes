"""
Graphe de randonnée gardé en mémoire pour le mode manuel.

En mode automatique, le graphe est chargé une fois par calcul. En mode manuel,
chaque point ajouté déclenche un appel : recharger 20 à 70 Mo de pickle (1 à 2 s)
et chercher le nœud le plus proche en parcourant tous les nœuds (~0,6 s) rendrait
le compteur de distance poussif. On garde donc le graphe du dernier massif
utilisé, avec un index spatial de ses nœuds.

Un graphe occupe plusieurs centaines de Mo et chaque worker Gunicorn a le sien :
il est libéré après IDLE_RELEASE_SECONDS sans utilisation.
"""

import logging
import math
import os
import pickle
import threading
import time

import numpy as np
from django.conf import settings
from scipy.spatial import cKDTree

from hello.data_preparation.utils import slugify

logger = logging.getLogger(__name__)

IDLE_RELEASE_SECONDS = 10 * 60


class MassifGraph:
    """Graphe d'un massif + index spatial de ses nœuds (lon, lat)."""

    def __init__(self, slug, G):
        self.slug = slug
        self.G = G
        self._nodes = list(G.nodes)
        coords = np.array(self._nodes, dtype=float)
        # Projection équirectangulaire locale : à l'échelle d'un massif, le plus
        # proche voisin en (lon·cos φ, lat) est celui en distance réelle.
        self._lon_scale = math.cos(math.radians(float(coords[:, 1].mean())))
        self._tree = cKDTree(np.c_[coords[:, 0] * self._lon_scale, coords[:, 1]])

    def nearest_node(self, lon, lat):
        _, index = self._tree.query([lon * self._lon_scale, lat])
        return self._nodes[int(index)]


_lock = threading.Lock()
_cached = None
_last_used = 0.0
_timer = None


def _release_if_idle():
    global _cached, _timer
    with _lock:
        _timer = None
        if _cached is None:
            return
        idle = time.monotonic() - _last_used
        if idle >= IDLE_RELEASE_SECONDS:
            logger.info(f"Mode manuel : graphe {_cached.slug} libéré après {idle:.0f} s d'inactivité")
            _cached = None
        else:
            _schedule_release(IDLE_RELEASE_SECONDS - idle)


def _schedule_release(delay):
    global _timer
    _timer = threading.Timer(delay, _release_if_idle)
    _timer.daemon = True
    _timer.start()


def get_massif_graph(massif):
    """Retourne le MassifGraph du massif, chargé au besoin (un seul massif en mémoire)."""
    global _cached, _last_used
    slug = slugify(massif)
    with _lock:
        if _cached is None or _cached.slug != slug:
            path = os.path.join(settings.BASE_DIR, "data", "output", f"{slug}_hiking_graph.gpickle")
            started = time.monotonic()
            # Libérer l'ancien graphe avant de charger le nouveau : pas deux en mémoire
            _cached = None
            with open(path, "rb") as fh:
                _cached = MassifGraph(slug, pickle.load(fh))
            logger.info(f"Mode manuel : graphe {slug} chargé en {time.monotonic() - started:.1f} s")
        _last_used = time.monotonic()
        if _timer is None:
            _schedule_release(IDLE_RELEASE_SECONDS)
        return _cached
