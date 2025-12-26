from django.shortcuts import render
from django.http import JsonResponse
from hello.services.trouver_chemin import compute_best_route
import traceback
import os
import json

def index(request):
    return render(request, "hello/index.html")

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
                randomness = float(randomness_str) / 2
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

            # `compute_best_route` now sauvegarde le geojson et le gpx et
            # ajoute la clé `generated_filename` au GeoJSON retourné.
            return JsonResponse(geojson_data)

        except Exception as e:
            print("❌ ERREUR SERVEUR INTERNE:")
            print(traceback.format_exc())
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Méthode non autorisée"}, status=405)


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
