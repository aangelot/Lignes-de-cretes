from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

from hello.services.trouver_chemin import compute_best_route, save_geojson

def index(request):
    return render(request, "hello/index.html")

@csrf_exempt
def get_route(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            city = data.get("city", "Lyon")
            massif = data.get("massif", "Chartreuse")
            level = data.get("level", "debutant")

            # Appel direct à la logique métier
            geojson_data = compute_best_route(city=city, massif=massif, level=level)

            # Sauvegarde facultative
            save_geojson(geojson_data)

            return JsonResponse(geojson_data)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)
