"""
Assemblage du trek manuel terminé : même GeoJSON que le mode automatique
(build_geojson), sauvegardé avec son GPX (save_result), pour que l'affichage
final (renderRoute) et le téléchargement soient identiques.
"""

from hello.data_preparation.utils import slugify
from hello.routing.utils.files_tools import build_geojson, save_result
from .hike import compute_hike, load_poi_geojson
from .stops import load_stops
from .transit import compute_back_for_stop

ROUTE_TYPE = "manual"


def finish_trek(massif, stop_id, poi_ids, return_stop_id, address, departure_time, return_time):
    """
    Trajet retour + tracé complet jusqu'à l'arrêt retour.

    Le trajet aller n'est pas recalculé (ce serait un second appel Google) : le
    navigateur l'a déjà et le réinjecte dans `properties.transit_go`.
    Retourne {"result": GeoJSON, "stop": arrêt retour}.
    """
    # Google d'abord : si l'arrêt n'est pas desservi, inutile de calculer le tracé.
    back = compute_back_for_stop(massif, return_stop_id, address, departure_time, return_time)
    hike = compute_hike(massif, stop_id, poi_ids, end_stop_id=return_stop_id)

    result = build_geojson(
        path=hike["coordinates"],
        dist=hike["distance_m"],
        route_type=ROUTE_TYPE,
        travel_go=None,
        travel_return=back["transit_back"],
        total_ascent=hike["ascent_m"],
        elevation_failed=hike["elevation_failed"],
        return_error_message=None,
        poi_data=load_poi_geojson(massif),
        start_stop_name=load_stops(massif).get(str(stop_id), {}).get("properties", {}).get("stop_name"),
        end_stop_name=back["stop"]["name"],
    )
    save_result(result, address, slugify(massif), "manuel", 0, None)
    return {"result": result, "stop": back["stop"]}
