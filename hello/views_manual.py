"""
API du mode manuel : l'utilisateur construit son trek étape par étape.
Les vues du mode automatique sont dans views.py.
"""

import traceback

from django.http import JsonResponse

from hello.routing.manual.stops import get_stops_with_durations
from hello.routing.manual.transit import compute_go_for_stop, NoTransitFound
from hello.routing.manual.hike import load_pois, compute_hike, UnreachablePoint
from hello.routing.manual.finish import finish_trek


def _require_get(request):
    if request.method != "GET":
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)
    return None


def manual_stops(request):
    """Arrêts du massif colorables selon la durée estimée depuis la gare."""
    if (error := _require_get(request)):
        return error

    massif = request.GET.get("massif", "")
    address = request.GET.get("address", "")
    try:
        return JsonResponse(get_stops_with_durations(massif, address))
    except (ValueError, FileNotFoundError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        print("❌ Erreur manual_stops:")
        print(traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)


def manual_transit_go(request):
    """Trajet aller vers l'arrêt de départ choisi (un appel Google)."""
    if (error := _require_get(request)):
        return error

    try:
        result = compute_go_for_stop(
            massif=request.GET.get("massif", ""),
            stop_id=request.GET.get("stop_id", ""),
            address=request.GET.get("address", ""),
            departure_time=request.GET.get("departure_datetime"),
            return_time=request.GET.get("return_datetime"),
        )
        return JsonResponse(result)
    except NoTransitFound as e:
        # Pas une erreur serveur : l'utilisateur doit choisir un autre arrêt.
        return JsonResponse({"error": str(e), "no_transit": True}, status=404)
    except (ValueError, TypeError, FileNotFoundError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        print("❌ Erreur manual_transit_go:")
        print(traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)


def manual_pois(request):
    """Points d'intérêt du massif, sélectionnables sur la carte."""
    if (error := _require_get(request)):
        return error

    try:
        return JsonResponse({"pois": load_pois(request.GET.get("massif", ""))})
    except FileNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        print("❌ Erreur manual_pois:")
        print(traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)


def _poi_ids(request):
    """`pois` : identifiants séparés par des virgules, dans l'ordre du tracé."""
    return [p for p in request.GET.get("pois", "").split(",") if p != ""]


def manual_hike(request):
    """
    Tracé arrêt de départ → POI choisis, prolongé jusqu'à `end_stop_id` s'il est
    fourni (aperçu de la marche vers un arrêt retour).
    """
    if (error := _require_get(request)):
        return error

    try:
        return JsonResponse(compute_hike(
            massif=request.GET.get("massif", ""),
            stop_id=request.GET.get("stop_id", ""),
            poi_ids=_poi_ids(request),
            end_stop_id=request.GET.get("end_stop_id") or None,
        ))
    except UnreachablePoint as e:
        return JsonResponse({"error": str(e), "unreachable": True}, status=422)
    except (ValueError, FileNotFoundError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        print("❌ Erreur manual_hike:")
        print(traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)


def manual_finish(request):
    """Arrêt retour validé : trajet retour (un appel Google) et trek complet."""
    if (error := _require_get(request)):
        return error

    try:
        return JsonResponse(finish_trek(
            massif=request.GET.get("massif", ""),
            stop_id=request.GET.get("stop_id", ""),
            poi_ids=_poi_ids(request),
            return_stop_id=request.GET.get("return_stop_id", ""),
            address=request.GET.get("address", ""),
            departure_time=request.GET.get("departure_datetime"),
            return_time=request.GET.get("return_datetime"),
        ))
    except NoTransitFound as e:
        return JsonResponse({"error": str(e), "no_transit": True}, status=404)
    except UnreachablePoint as e:
        return JsonResponse({"error": str(e), "unreachable": True}, status=422)
    except (ValueError, TypeError, FileNotFoundError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        print("❌ Erreur manual_finish:")
        print(traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)
