import re
import unicodedata


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