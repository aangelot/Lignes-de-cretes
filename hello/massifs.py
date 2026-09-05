"""Contours simplifiés des massifs actifs, pour l'affichage et la sélection sur la carte.

`data/input/massifs.geojson` pèse plusieurs Mo, contient tous les PNR de France et
n'est pas déployé en production (le dossier `data/` est exclu de l'image Docker et
fourni par un volume). On en extrait donc les seuls massifs de `ACTIVE_MASSIFS`, avec
une géométrie simplifiée, dans un fichier léger **versionné avec le code** :
`hello/data/massifs_actifs.geojson`.

Ce fichier est régénéré automatiquement en développement dès que `ACTIVE_MASSIFS`
change : sa signature est comparée à la liste courante à chaque appel. Il fait donc
partie du changement — quand on ouvre un nouveau massif, on commite `constants.py`
et ce fichier ensemble.

En production la source n'existe pas : la signature correspond déjà et le fichier est
servi tel quel. Si elle ne correspondait pas (constante modifiée sans régénération),
on sert les contours disponibles restreints aux massifs ouverts plutôt que d'échouer.
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
CACHE_FILENAME = os.path.join("hello", "data", "massifs_actifs.geojson")


def _source_path():
    """Source volumineuse, présente uniquement en développement."""
    return os.path.join(settings.BASE_DIR, SOURCE_FILENAME)


def _cache_path():
    """Fichier léger versionné, livré avec le code."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "massifs_actifs.geojson")


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
    """Écrit le fichier de façon atomique (plusieurs requêtes peuvent le régénérer)."""
    path = _cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
            fh.write("\n")
        # mkstemp crée en 0600 : ce fichier est versionné et embarqué dans l'image
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _read_cache():
    try:
        with open(_cache_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _restricted_to_active(cached):
    """Contours du fichier versionné restreints aux massifs actuellement ouverts."""
    by_value = {
        f.get("properties", {}).get("value"): f for f in cached.get("features", [])
    }
    features, missing = [], []
    for massif in ACTIVE_MASSIFS:
        feature = by_value.get(massif["value"])
        if feature:
            features.append(feature)
        else:
            missing.append(massif["value"])
    return features, missing


def get_active_massifs_geojson():
    """Retourne le GeoJSON des massifs actifs, en le régénérant si besoin."""
    cached = _read_cache()
    if cached and cached.get("signature") == _signature():
        return cached

    try:
        data = _build_geojson()
    except OSError as exc:
        # Production : la source volumineuse n'est pas déployée. On sert ce dont on
        # dispose plutôt que d'échouer — la carte perd au pire un contour, jamais le
        # formulaire. Un massif ouvert sans contour signale un fichier à régénérer.
        if cached is None:
            print(f"⚠️ Contours des massifs indisponibles : {exc}")
            return {"type": "FeatureCollection", "features": []}

        features, missing = _restricted_to_active(cached)
        if missing:
            print(
                f"⚠️ {CACHE_FILENAME} est périmé : aucun contour pour "
                f"{', '.join(missing)}. Régénérer et commiter le fichier."
            )
        return {"type": "FeatureCollection", "features": features}

    _write_cache(data)
    return data
