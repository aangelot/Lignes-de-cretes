"""
Ajoute l'altitude de chaque nœud au graphe de randonnée d'un massif.

Les nœuds du graphe sont des tuples (lon, lat) et constituent l'intégralité des
points des tracés calculés par l'application : stocker l'altitude en attribut de
nœud permet au calcul d'itinéraire de la lire directement, sans appel API.

Source principale : RGE ALTI via la Géoplateforme IGN (résolution 1 à 5 m).
Source de repli : Open-Elevation, pour les nœuds situés hors couverture IGN
(versants italiens et suisses des massifs frontaliers).

Le script est idempotent : sans --force, seuls les nœuds sans altitude sont
interrogés, ce qui permet de reprendre une exécution interrompue.

Usage : python Graphe_3_altitudes.py "<Nom du massif>" [--force] [--workers N]
"""

import argparse
import os
import pickle
import shutil
import sys
import time

from concurrent.futures import ThreadPoolExecutor

import requests

from utils import slugify

IGN_URL = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
IGN_RESOURCE = "ign_rge_alti_wld"
IGN_BATCH = 5000  # maximum accepté par l'API

OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
OPEN_ELEVATION_BATCH = 1000

# L'IGN renvoie -99999 pour un point hors couverture
NO_DATA_THRESHOLD = -1000

MAX_ATTEMPTS = 3
ELEVATION_ATTR = "ele"


class _Failed:
    """Sentinelle : le lot n'a pas pu être interrogé (≠ point hors couverture)."""
    def __repr__(self):
        return "FAILED"


FAILED = _Failed()


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _clean(value):
    """Normalise une altitude : None si absente ou hors couverture."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if value < NO_DATA_THRESHOLD else value


def _fetch_ign(session, nodes):
    """Interroge l'IGN pour un lot de nœuds. Retourne une liste de float|None."""
    payload = {
        "lon": "|".join(f"{lon:.6f}" for lon, _ in nodes),
        "lat": "|".join(f"{lat:.6f}" for _, lat in nodes),
        "resource": IGN_RESOURCE,
        "delimiter": "|",
        "zonly": "true",
        "measures": "false",
        "indent": "false",
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.post(IGN_URL, json=payload, timeout=180)
            response.raise_for_status()
            elevations = response.json().get("elevations")
            if not isinstance(elevations, list) or len(elevations) != len(nodes):
                raise ValueError(f"réponse IGN inattendue ({len(elevations) if isinstance(elevations, list) else type(elevations).__name__})")
            return [_clean(e) for e in elevations]
        except Exception as e:
            print(f"    ⚠️ IGN tentative {attempt}/{MAX_ATTEMPTS} : {type(e).__name__} {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 * attempt)

    # Lot injoignable : on ne conclut pas que les points sont hors couverture
    return [FAILED] * len(nodes)


def _fetch_open_elevation(session, nodes):
    """Interroge Open-Elevation pour un lot de nœuds. Retourne une liste de float|None."""
    payload = {"locations": [{"latitude": lat, "longitude": lon} for lon, lat in nodes]}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.post(OPEN_ELEVATION_URL, json=payload, timeout=180)
            response.raise_for_status()
            results = response.json().get("results")
            if not isinstance(results, list) or len(results) != len(nodes):
                raise ValueError("réponse Open-Elevation inattendue")
            return [_clean(r.get("elevation")) for r in results]
        except Exception as e:
            print(f"    ⚠️ Open-Elevation tentative {attempt}/{MAX_ATTEMPTS} : {type(e).__name__} {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 * attempt)

    return [FAILED] * len(nodes)


def fetch_elevations(nodes, fetcher, batch_size, workers, label):
    """
    Récupère les altitudes d'une liste de nœuds via `fetcher`, par lots parallélisés.
    Retourne (altitudes, injoignables) où `altitudes` est un dict {noeud: altitude}
    des points renseignés et `injoignables` l'ensemble des nœuds dont le lot n'a pas
    pu être interrogé — à distinguer des points explicitement hors couverture.
    """
    batches = list(_chunks(nodes, batch_size))
    print(f"  📡 {label} : {len(nodes)} points en {len(batches)} lots ({workers} en parallèle)")

    elevations = {}
    unreachable = set()
    done = 0
    started = time.time()

    with requests.Session() as session:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for batch, results in zip(batches, pool.map(lambda b: fetcher(session, b), batches)):
                for node, elevation in zip(batch, results):
                    if elevation is FAILED:
                        unreachable.add(node)
                    elif elevation is not None:
                        elevations[node] = elevation
                done += 1
                if done % 10 == 0 or done == len(batches):
                    elapsed = time.time() - started
                    eta = elapsed / done * (len(batches) - done)
                    print(f"    lot {done}/{len(batches)} — {len(elevations)} altitudes — écoulé {elapsed/60:.1f} min, reste ~{eta/60:.1f} min")

    if unreachable:
        print(f"  ⚠️ {len(unreachable)} points dans des lots injoignables, laissés sans altitude")

    return elevations, unreachable


def add_elevations(massif_name: str, force: bool = False, workers: int = 4):
    massif_slug = slugify(massif_name)
    graph_path = f"data/output/{massif_slug}_hiking_graph.gpickle"

    if not os.path.exists(graph_path):
        print(f"❌ Graphe introuvable : {graph_path}")
        sys.exit(1)

    print(f"📂 Chargement de {graph_path}")
    with open(graph_path, "rb") as f:
        G = pickle.load(f)
    print(f"  {G.number_of_nodes()} nœuds, {G.number_of_edges()} arêtes")

    if force:
        todo = list(G.nodes)
    else:
        todo = [n for n in G.nodes if G.nodes[n].get(ELEVATION_ATTR) is None]
        already = G.number_of_nodes() - len(todo)
        if already:
            print(f"  ⤷ {already} nœuds ont déjà une altitude, ils sont ignorés (--force pour tout recalculer)")

    if not todo:
        print("✅ Tous les nœuds ont déjà une altitude, rien à faire.")
        return

    elevations, unreachable = fetch_elevations(todo, _fetch_ign, IGN_BATCH, workers, "IGN RGE ALTI")

    # Seuls les points que l'IGN déclare explicitement hors couverture partent vers
    # Open-Elevation : ceux dont le lot a échoué restent sans altitude et seront
    # réessayés auprès de l'IGN au prochain lancement.
    out_of_range = [n for n in todo if n not in elevations and n not in unreachable]
    if out_of_range:
        print(f"  🌍 {len(out_of_range)} nœuds hors couverture IGN ({100*len(out_of_range)/len(todo):.1f} %) — repli Open-Elevation")
        fallback, _ = fetch_elevations(out_of_range, _fetch_open_elevation, OPEN_ELEVATION_BATCH, workers, "Open-Elevation")
        elevations.update(fallback)

    for node, elevation in elevations.items():
        G.nodes[node][ELEVATION_ATTR] = elevation

    with_elevation = sum(1 for n in G.nodes if G.nodes[n].get(ELEVATION_ATTR) is not None)
    still_missing = G.number_of_nodes() - with_elevation
    print(f"  📊 {with_elevation}/{G.number_of_nodes()} nœuds avec altitude ({100*with_elevation/G.number_of_nodes():.2f} %)")
    if still_missing:
        print(f"  ⚠️ {still_missing} nœuds restent sans altitude — relancer le script pour réessayer")

    if not elevations:
        print("❌ Aucune altitude récupérée, le graphe n'est pas réécrit.")
        sys.exit(1)

    # Sauvegarde du graphe d'origine avant la première réécriture
    backup_path = f"{graph_path}.bak"
    if not os.path.exists(backup_path):
        print(f"💾 Sauvegarde de l'original dans {backup_path}")
        shutil.copy2(graph_path, backup_path)

    # Écriture atomique pour ne pas laisser un graphe tronqué en cas d'interruption
    tmp_path = f"{graph_path}.tmp"
    with open(tmp_path, "wb") as f:
        pickle.dump(G, f)
    os.replace(tmp_path, graph_path)

    print(f"✅ Altitudes ajoutées au graphe : {graph_path} ({os.path.getsize(graph_path)/1e6:.1f} Mo)")


def main():
    parser = argparse.ArgumentParser(description="Ajoute l'altitude aux nœuds du graphe de randonnée d'un massif.")
    parser.add_argument("massif", help="Nom du massif")
    parser.add_argument("--force", action="store_true", help="Recalcule toutes les altitudes, même déjà présentes")
    parser.add_argument("--workers", type=int, default=4, help="Nombre de lots interrogés en parallèle (défaut : 4)")
    args = parser.parse_args()

    add_elevations(args.massif, force=args.force, workers=args.workers)


if __name__ == "__main__":
    main()
