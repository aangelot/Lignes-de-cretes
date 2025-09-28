import re

def slugify(name: str) -> str:
    """Transforme une chaîne en identifiant safe pour les fichiers"""
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip("_")