import traceback
import os
import json
import csv
import uuid
import threading
from datetime import datetime
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse
from hello.services.trouver_chemin import compute_best_route
from hello.services.progress import initialize_route_status, update_route_status, get_route_status
from hello.constants import RANDOMNESS_OPTIONS, RANDOMNESS_DEFAULT


def index(request):
    return render(request, "hello/index.html", {
        "randomness_options": RANDOMNESS_OPTIONS,
        "randomness_default": RANDOMNESS_DEFAULT,
    })

def log_get_route_call(massif, address, level, randomness_str, departure_datetime, return_datetime, transit_priority, result):
    """Enregistre l'appel à get_route dans un fichier CSV."""
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    csv_file = os.path.join(logs_dir, "appels_get_route.csv")
    
    # Vérifier si le fichier existe pour ajouter l'en-tête si nécessaire
    file_exists = os.path.isfile(csv_file)
    
    with open(csv_file, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["date_appel", "massif", "address", "level", "randomness", "departure_datetime", "return_datetime", "transit_priority", "resultat"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        if not file_exists:
            writer.writeheader()
        
        writer.writerow({
            "date_appel": datetime.now().isoformat(),
            "massif": massif,
            "address": address,
            "level": level,
            "randomness": randomness_str,
            "departure_datetime": departure_datetime,
            "return_datetime": return_datetime,
            "transit_priority": transit_priority,
            "resultat": result
        })

def get_route(request):
    if request.method == "GET":
        try:
            massif = request.GET.get("massif", "Chartreuse")
            address = request.GET.get("address", "")
            level = request.GET.get("level", "debutant")
            randomness_str = request.GET.get("randomness", "0.3")
            departure_datetime = request.GET.get("departure_datetime")
            return_datetime = request.GET.get("return_datetime")
            transit_priority = request.GET.get("transit_priority", "")

            # --- Conversion du paramètre randomness ---
            try:
                print(f"Paramètre 'randomness' reçu: '{randomness_str}'")
                randomness = float(randomness_str) / 2
                print(f"Paramètre 'randomness' converti: {randomness}")
                if not (0 <= randomness <= 1):
                    randomness = 0.25
            except ValueError:
                randomness = 0.25

            print(
                f"Appel get_route avec massif={massif}, level={level}, "
                f"randomness={randomness}, departure_datetime={departure_datetime}, "
                f"return_datetime={return_datetime}, address='{address}', "
                f"transit_priority='{transit_priority}'"
            )

            # --- Appel logique principale ---
            geojson_data = compute_best_route(
                randomness=randomness,
                massif=massif,
                departure_time=departure_datetime,
                return_time=return_datetime,
                level=level,
                address=address,
                transit_priority=transit_priority,
            )
            print("Itinéraire calculé avec succès.")

            # Enregistrement du succès
            log_get_route_call(massif, address, level, randomness_str, departure_datetime, return_datetime, transit_priority, "Succès")

            # `compute_best_route` now sauvegarde le geojson et le gpx et
            # ajoute la clé `generated_filename` au GeoJSON retourné.
            return JsonResponse(geojson_data)

        except Exception as e:
            print("❌ ERREUR SERVEUR INTERNE:")
            print(traceback.format_exc())
            
            # Enregistrement de l'erreur
            log_get_route_call(massif, address, level, randomness_str, departure_datetime, return_datetime, transit_priority, str(e))
            
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Méthode non autorisée"}, status=405)


def start_route(request):
    if request.method != "GET":
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)

    request_id = uuid.uuid4().hex
    initialize_route_status(request_id, "Démarrage du calcul du tracé...", 0)

    massif = request.GET.get("massif", "Chartreuse")
    address = request.GET.get("address", "")
    level = request.GET.get("level", "debutant")
    randomness_str = request.GET.get("randomness", "0.3")
    departure_datetime = request.GET.get("departure_datetime")
    return_datetime = request.GET.get("return_datetime")
    transit_priority = request.GET.get("transit_priority", "")

    try:
        randomness = float(randomness_str) / 2
        if not (0 <= randomness <= 1):
            randomness = 0.25
    except ValueError:
        randomness = 0.25

    def status_callback(message, progress=None):
        update_route_status(request_id, message=message, progress=progress)

    def worker():
        try:
            geojson_data = compute_best_route(
                randomness=randomness,
                massif=massif,
                departure_time=departure_datetime,
                return_time=return_datetime,
                level=level,
                address=address,
                transit_priority=transit_priority,
                status_callback=status_callback,
            )
            log_get_route_call(massif, address, level, randomness_str, departure_datetime, return_datetime, transit_priority, "Succès")
            update_route_status(request_id, message="Calcul terminé", progress=100, finished=True, result=geojson_data)
        except Exception as exc:
            error_message = str(exc)
            print("❌ ERREUR SERVEUR INTERNE (background):")
            print(traceback.format_exc())
            log_get_route_call(massif, address, level, randomness_str, departure_datetime, return_datetime, transit_priority, error_message)
            update_route_status(request_id, message=f"Erreur : {error_message}", progress=100, finished=True, error=error_message)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    return JsonResponse({"request_id": request_id})


def route_status(request):
    if request.method != "GET":
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)

    request_id = request.GET.get("request_id")
    if not request_id:
        return JsonResponse({"error": "request_id requis"}, status=400)

    status_data = get_route_status(request_id)
    if status_data is None:
        return JsonResponse({"error": "Demande introuvable"}, status=404)

    return JsonResponse(status_data)


def gares_list(request):
    """Retourne une liste simplifiée des gares pour l'autocomplete.
    Format: [{"name": ..., "code_uic": ..., "lon": ..., "lat": ...}, ...]
    """
    if request.method != "GET":
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)

    try:
        # Détecte le chemin vers le fichier data/input/liste-des-gares.geojson
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, ".."))
        geojson_path = os.path.join(project_root, "data", "input", "liste-des-gares.geojson")

        with open(geojson_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        results = []
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            libelle = props.get("libelle") or props.get("name") or ""
            code = props.get("code_uic") or props.get("idgaia")
            # geometry coordinates [lon, lat]
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") if geom else None
            lon = coords[0] if coords and len(coords) >= 2 else None
            lat = coords[1] if coords and len(coords) >= 2 else None

            if libelle:
                results.append({"name": libelle, "code_uic": code, "lon": lon, "lat": lat})

        return JsonResponse(results, safe=False)

    except Exception as e:
        print("Erreur gares_list:", e)
        return JsonResponse({"error": str(e)}, status=500)
