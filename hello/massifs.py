"""Contours simplifiés des massifs actifs, pour l'affichage et la sélection sur la carte.

`data/input/massifs.geojson` pèse plusieurs Mo et contient tous les PNR de France :
impossible de l'envoyer au navigateur. On en extrait donc les seuls massifs de
`ACTIVE_MASSIFS`, avec une géométrie simplifiée, dans un fichier de cache.

Ce cache est régénéré automatiquement dès que `ACTIVE_MASSIFS` change : sa signature
est stockée dans le fichier produit et comparée à chaque appel. Ajouter un massif dans
`hello/constants.py` suffit donc, rien n'est à relancer à la main.
"""

import hashlib
import json
import os
import tempfile

from django.conf import settings
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from hello.constants import ACTIVE_MASSIFS
from hello.data_preparation.utils import normalize_label

# Tolérance de simplification en degrés (~100 m) : assez fin pour reconnaître un
# massif à l'œil, assez grossier pour diviser le poids du fichier par ~20.
SIMPLIFY_TOLERANCE_DEG = 0.001

SOURCE_FILENAME = os.path.join("data", "input", "massifs.geojson")
CACHE_FILENAME = os.path.join("data", "output", "massifs_actifs.geojson")                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   


def _source_path():
    return os.path.join(settings.BASE_DIR, SOURCE_FILENAME)


def _cache_path():
    return os.path.join(settings.BASE_DIR, CACHE_FILENAME)


def _signature():
    """Empreinte de la configuration courante : liste des massifs + tolérance."""
    payload = json.dumps(
        {
            "massifs": [[m["value"], m["label"]] for m in ACTIVE_MASSIFS],
            "tolerance": SIMPLIFY_TOLERANCE_DEG,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _feature_name(properties):
    return properties.get("DRGP_L_LIB") or properties.get("nom_site") or ""


def _build_geojson():
    """Extrait et simplifie les contours des massifs actifs depuis la source."""
    with open(_source_path(), "r", encoding="utf-8") as fh:
        source = json.load(fh)

    # Un massif peut être découpé en plusieurs features dans la source : on les
    # regroupe par nom normalisé pour n'en produire qu'un seul contour.
    geometries_by_name = {}
    for feature in source.get("features", []):
        geometry = feature.get("geometry")
        if not geometry:
            continue
        key = normalize_label(_feature_name(feature.get("properties", {})))
        if key:
            geometries_by_name.setdefault(key, []).append(shape(geometry))

    features = []
    missing = []
    for massif in ACTIVE_MASSIFS:
        geometries = geometries_by_name.get(normalize_label(massif["value"]))
        if not geometries:
            missing.append(massif["value"])
            continue

        merged = unary_union(geometries).simplify(
            SIMPLIFY_TOLERANCE_DEG, preserve_topology=True
        )
        features.append({
            "type": "Feature",
            "properties": {"value": massif["value"], "label": massif["label"]},
            "geometry": mapping(merged),
        })

    if missing:
        print(f"⚠️ Contours introuvables dans {SOURCE_FILENAME} pour : {', '.join(missing)}")

    return {"type": "FeatureCollection", "signature": _signature(), "features": features}


def _write_cache(data):
    """Écrit le cache de façon atomique (plusieurs requêtes peuvent le régénérer)."""
    path = _cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def get_active_massifs_geojson():
    """Retourne le GeoJSON des massifs actifs, en le générant si le cache est périmé."""
    path = _cache_path()

    try:
        with open(path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        if cached.get("signature") == _signature():
            return cached
    except (OSError, json.JSONDecodeError):
        pass

    data = _build_geojson()
    _write_cache(data)
    return data
