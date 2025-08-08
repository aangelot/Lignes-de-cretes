from django.shortcuts import render
from django.http import JsonResponse
from hello.services.trouver_chemin import compute_best_route, save_geojson

def index(request):
    return render(request, "hello/index.html")

def get_route(request):
    if request.method == "GET":
        try:
            city = request.GET.get("city", "Lyon")
            massif = request.GET.get("massif", "Chartreuse")
            level = request.GET.get("level", "debutant")
            randomness_str = request.GET.get("randomness", "0.3")

            try:
                randomness = float(randomness_str)
                if not (0 <= randomness <= 1):
                    randomness = 0.3
            except ValueError:
                randomness = 0.3

            # Appel direct à la logique métier avec randomness
            geojson_data = compute_best_route(city=city, massif=massif, level=level, randomness=randomness)

            # Sauvegarde facultative
            save_geojson(geojson_data)

            return JsonResponse(geojson_data)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)
