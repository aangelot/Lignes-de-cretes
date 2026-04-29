import json
import os
from datetime import datetime
from django.conf import settings

STATUS_DIR = os.path.join(settings.BASE_DIR, "data", "logs", "route_status")


def ensure_status_dir():
    os.makedirs(STATUS_DIR, exist_ok=True)


def status_file_path(request_id):
    ensure_status_dir()
    return os.path.join(STATUS_DIR, f"{request_id}.json")


def _write_json_atomic(path, data):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def initialize_route_status(request_id, message="Démarrage du calcul du tracé...", progress=0):
    path = status_file_path(request_id)
    state = {
        "request_id": request_id,
        "status": message,
        "progress": progress,
        "finished": False,
        "error": None,
        "result": None,
        "updated_at": datetime.utcnow().isoformat() + "Z"
    }
    _write_json_atomic(path, state)
    return state


def update_route_status(request_id, message=None, progress=None, finished=None, error=None, result=None):
    path = status_file_path(request_id)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except FileNotFoundError:
        state = {
            "request_id": request_id,
            "status": "Statut introuvable",
            "progress": 0,
            "finished": False,
            "error": None,
            "result": None,
            "updated_at": datetime.utcnow().isoformat() + "Z"
        }

    if message is not None:
        state["status"] = message
    if progress is not None:
        state["progress"] = progress
    if finished is not None:
        state["finished"] = bool(finished)
    if error is not None:
        state["error"] = error
    if result is not None:
        state["result"] = result
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _write_json_atomic(path, state)
    return state


def get_route_status(request_id):
    path = status_file_path(request_id)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
