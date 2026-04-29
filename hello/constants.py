"""Constantes partagées pour le back-office et services."""

# Poids d'évaluation des itinéraires de transport en commun
TRANSIT_WEIGHTS = {
    "balanced": {"duration": 0.7, "elevation": 0.15, "nature": 0.15},
    "fast": {"duration": 0.95, "elevation": 0.025, "nature": 0.025},
    "deep_nature": {"duration": 0.2, "elevation": 0.3, "nature": 0.5},
}

# Paramètres de tolérance et autres constantes métier (à étendre si besoin)
TRANSIT_FAILURE_THRESHOLD = 20
MINIMAL_WALK_HOURS = 4
MAX_DEPARTURE_DELAY_EVENING_HOURS = 18
MAX_DEPARTURE_DELAY_DAY_HOURS = 6

LEVEL_DISTANCE_MAP = {
    'debutant': 8_000,
    'intermediaire': 16_000,
    'avance': 25_000,
    'expert': 40_000,
}

# Pour le choix de l'arrêt retour en fonction de la distance à la fin de la randonnée
RETURN_STOP_MAX_DISTANCE_RATIO = 0.6

# Seuil de consommation de distance pour arrêter l'ajout de POI (en %)
HIKE_DISTANCE_CONSUMPTION_THRESHOLD = 0.9

# Rando : marche à pied
WALK_SECONDS_PER_DAY = 10 * 3600
MIN_DISTANCE_DAY1 = 5_000

# Options du paramètre randomness du front
RANDOMNESS_OPTIONS = [
    {"value": "0", "label": "🧭 Itinéraire classique (les bases)"},
    {"value": "0.2", "label": "⚖️ Équilibre entre logique et surprise"},
    {"value": "0.5", "label": "🌿 Exploration (hors sentiers connus)"},
    {"value": "1", "label": "🔥 Aventure totale (imprévisible)"},
]
RANDOMNESS_DEFAULT = "0.2"

# Algorithme de randonnée : pénalité pour dissuader la réutilisation d'arêtes
REUSE_PENALTY_MULTIPLIER = 5.0
