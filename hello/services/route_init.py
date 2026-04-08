import json
import os
from datetime import datetime, timedelta, time as dtime
from django.conf import settings
from hello.management.commands.utils import slugify
from hello.constants import LEVEL_DISTANCE_MAP, WALK_SECONDS_PER_DAY, MIN_DISTANCE_DAY1


def get_massif_diagonal_km(massif_name):
    """
    Lit la diagonale du massif depuis massifs_coord_max.geojson.
    """
    file_path = os.path.join(settings.BASE_DIR, "data", "input", "massifs_coord_max.geojson")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    massif_name =slugify(massif_name)
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if slugify(props.get("nom_pnr", "")) == massif_name:
            return float(props.get("diagonal_km"))

    raise RuntimeError(f"Diagonale introuvable pour le massif '{massif_name}'")


def choose_route_type(distance_max_m, diagonal_km):
    """
    crossing si distance inférieure à la diagonale du massif,
    sinon logique tour progressif.
    """

    distance_km = distance_max_m / 1000

    if distance_km < diagonal_km:
        return "crossing"

    return "massif_tour"


def compute_max_hiking_distance(departure_time, return_time, level, transit_route=None, return_transit_seconds=None):
    """
    Calcule la distance maximale de randonnée possible en fonction des informations 
    de transport en commun et du niveau de difficulté souhaité.

    return_transit_seconds : indique explicitement le temps de retour TC à utiliser (si connu).
    """

    if level not in LEVEL_DISTANCE_MAP:
        raise ValueError(f"Niveau inconnu: {level}")

    dist_per_day = LEVEL_DISTANCE_MAP[level]

    nb_days = (return_time.date() - departure_time.date()).days + 1

    max_walk_seconds_per_day = WALK_SECONDS_PER_DAY
    min_distance_day1 = MIN_DISTANCE_DAY1

    transit_arrival_time = departure_time
    if transit_route is not None:
        steps = transit_route[0]["routes"][0]["legs"][0]["steps"]
        transit_steps = [s for s in steps if s["travelMode"] == "TRANSIT"]

        if transit_steps:
            last_transit = transit_steps[-1]
            arrival_str = last_transit["transitDetails"]["stopDetails"]["arrivalTime"]
            transit_arrival_time = datetime.fromisoformat(
                arrival_str.replace("Z", "+00:00")
            ).replace(tzinfo=None)

    seconds_available_first_day = max_walk_seconds_per_day - max(
        0, (transit_arrival_time - departure_time).total_seconds()
    )

    fraction_day1 = max(0, seconds_available_first_day / max_walk_seconds_per_day)
    distance_day1 = max(min_distance_day1, dist_per_day * fraction_day1)

    if return_transit_seconds is not None:
        transit_seconds_return = int(return_transit_seconds)
    elif transit_route is not None:
        duration_str = transit_route[0]["routes"][0]["legs"][0]["duration"]
        transit_seconds_return = int(duration_str.replace("s", ""))
    else:
        transit_seconds_return = 0

    end_walk = return_time - timedelta(seconds=transit_seconds_return)
    start_walk = datetime.combine(
        return_time.date(),
        dtime(8, 0),
        tzinfo=return_time.tzinfo
    )

    available_seconds = (end_walk - start_walk).total_seconds()
    fraction_last_day = max(0, available_seconds / max_walk_seconds_per_day)
    distance_last_day = max(min_distance_day1, dist_per_day * fraction_last_day)

    if nb_days == 1:
        distance_max_m = distance_day1
    else:
        distance_max_m = (
            distance_day1
            + dist_per_day * (nb_days - 2)
            + distance_last_day
        )

    return distance_max_m


def initialize_route_parameters(
    massif_name,
    departure_time,
    return_time,
    level,
    transit_route=None,
    return_transit_seconds=None
):
    """
    Retourne :
    distance_max_m, diagonal_km, route_type
    """

    diagonal_km = get_massif_diagonal_km(massif_name)

    distance_max_m = compute_max_hiking_distance(
        departure_time=departure_time,
        return_time=return_time,
        level=level,
        transit_route=transit_route,
        return_transit_seconds=return_transit_seconds
    )

    route_type = choose_route_type(distance_max_m, diagonal_km)

    return distance_max_m, route_type