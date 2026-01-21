"""
Gestion des messages de progression pour les calculs d'itinéraires.
"""

# Stockage global des messages (en mémoire pour la session)
_progress_messages = []

def add_progress_message(message: str):
    """Ajoute un message de progression."""
    global _progress_messages
    _progress_messages = [message]  # Écraser le précédent message
    print(f"📊 Progression: {message}")

def get_progress_messages():
    """Récupère et réinitialise les messages."""
    global _progress_messages
    messages = _progress_messages[:]
    _progress_messages = []
    return messages

def reset_progress():
    """Réinitialise les messages de progression."""
    global _progress_messages
    _progress_messages = []

def get_current_message():
    """Retourne le dernier message de progression."""
    global _progress_messages
    return _progress_messages[-1] if _progress_messages else None
