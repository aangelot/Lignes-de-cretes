from django.shortcuts import render
from django.http import JsonResponse
from hello.services.trouver_chemin_2 import compute_best_route, save_geojson

def index(request):
    return render(request, "hello/index.html")

def get_route(request):
    if request.method == "GET":
        try:
            city = request.GET.get("city", "Lyon")
            level = request.GET.get("level", "debutant")
            randomness_str = request.GET.get("randomness", "0.3")
            departure_datetime = request.GET.get("departure_datetime")
            return_datetime = request.GET.get("return_datetime")
            # Conversion du paramètre randomness
            try:
                randomness = float(randomness_str)
                if not (0 <= randomness <= 1):
                    randomness = 0.3
            except ValueError:
                randomness = 0.3

            # Appel à la logique métier avec les nouveaux paramètres
            print(f"Appel get_route avec city={city}, level={level}, randomness={randomness}, departure_datetime={departure_datetime}, return_datetime={return_datetime}")  
            geojson_data = compute_best_route(
                randomness=randomness,
                city=city,
                departure_time=departure_datetime,
                return_time=return_datetime,
                level=level,
            )

            # Sauvegarde facultative
            save_geojson(geojson_data)

            return JsonResponse(geojson_data)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)
