from django.shortcuts import render
from django.http import JsonResponse
from hello.services.trouver_chemin import compute_best_route, save_geojson_gpx
import traceback

def index(request):
    return render(request, "hello/index.html")

def get_route(request):
    if request.method == "GET":
        try:
            city = request.GET.get("city", "Lyon")
            massif = request.GET.get("massif", "Chartreuse")
            level = request.GET.get("level", "debutant")
            randomness_str = request.GET.get("randomness", "0.3")
            departure_datetime = request.GET.get("departure_datetime")
            return_datetime = request.GET.get("return_datetime")

            # --- Conversion du paramètre randomness ---
            try:
                randomness = float(randomness_str)/2
                if not (0 <= randomness <= 1):
                    randomness = 0.25
            except ValueError:
                randomness = 0.25

            print(f"Appel get_route avec city={city}, massif={massif}, level={level}, randomness={randomness}, "
                  f"departure_datetime={departure_datetime}, return_datetime={return_datetime}")

            # --- Appel de la logique principale ---
            geojson_data = compute_best_route(
                randomness=randomness,
                city=city,
                massif=massif,
                departure_time=departure_datetime,
                return_time=return_datetime,
                level=level,
            )
            print("✅ Itinéraire calculé avec succès.")

            save_geojson_gpx(geojson_data)

            # --- Réponse JSON ---
            return JsonResponse(geojson_data)

        except Exception as e:
            print("❌ ERREUR SERVEUR INTERNE:")
            print(traceback.format_exc())
            return JsonResponse({"error": str(e)}, status=500)

    else:
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)
