"""
Mode POI : construction d'un itinéraire contraint par points d'intérêt.
"""

import math
import random
import json
import os
import time
from shapely.geometry import Point
from networkx import shortest_path
from django.conf import settings

from .geotools import find_nearest_node, haversine
from .transit import (
    get_best_transit_route,
    get_transit_route_for_stop,
    choose_return_stop,
    compute_return_transit,
)
from .progress import update_status
from .hiking import _get_massif_center
from .route_init import initialize_route_parameters
from hello.constants import REUSE_PENALTY_MULTIPLIER


def compute_best_route_with_poi(
    randomness,
    massif,
    departure_time,
    return_time,
    level,
    address,
    transit_priority,
    pois,
    stops_data,
    G,
    poi_data,
    hubs_entree_data,
    status_callback=None,
):
    print("🚀 [POI MODE] Début compute_best_route_with_poi")
    print(f"📌 massif={massif}, nb_pois_demandés={len(pois)}")

    # ==========================================================
    # 1. EXTRACTION POI
    # ==========================================================
    poi_features = poi_data.get("features", [])
    print(f"📦 POI disponibles dans dataset: {len(poi_features)}")

    selected_pois = []
    for feat in poi_features:
        title = feat["properties"].get("titre")
        if title in pois:
            lon, lat = feat["geometry"]["coordinates"]
            node = find_nearest_node(G, (lat, lon))

            selected_pois.append({
                "id": title,
                "coord": (lon, lat),
                "node": node,
                "properties": feat.get("properties", {}),
            })
            print(f"✅ POI sélectionné: {title} -> coord=({lat}, {lon}), node={node}")

    print(f"🎯 Total POI retenus: {len(selected_pois)}")

    if not selected_pois:
        print("❌ ERREUR: aucun POI valide trouvé")
        raise RuntimeError("Aucun POI valide trouvé")

    # ==========================================================
    # 2. TRI POLAIRE (centre massif)
    # ==========================================================
    center_lon, center_lat = _get_massif_center(massif)
    print(f"📍 Centre massif: {(center_lon, center_lat)}")

    def _angle(poi):
        lon, lat = poi["coord"]
        return math.atan2(lat - center_lat, lon - center_lon)

    selected_pois.sort(key=_angle)
    print("🔄 POI triés par angle autour du massif")

    update_status("POI ordonnés géographiquement", status_callback, 15)

    # ==========================================================
    # 3. CHOIX DIRECTION
    # ==========================================================
    roll = random.random()
    print(f"🎲 random direction roll={roll}")

    if roll < 0.5:
        selected_pois = list(reversed(selected_pois))
        print("🔁 ordre POI inversé")

    start_poi = selected_pois[0]
    print(f"🚩 POI départ: {start_poi['id']}")

    # ==========================================================
    # 4. CHAÎNAGE POI → POI
    # ==========================================================

    # Arêtes déjà parcourues — mises à jour après chaque segment pour pénaliser les allers-retours
    traversed_edges: set = set()

    def penalized_weight(u, v, data):
        base = data.get("length", 1)
        return base * REUSE_PENALTY_MULTIPLIER if (u, v) in traversed_edges else base

    full_path_nodes = []
    current_node = start_poi["node"]

    full_path_nodes.append(current_node)
    print(f"🧭 node départ: {current_node}")

    for i, poi in enumerate(selected_pois[1:], 1):
        print(f"➡️ Segment POI {i}: {poi['id']} (node={poi['node']})")

        try:
            segment = shortest_path(G, current_node, poi["node"], weight=penalized_weight)
            print(f"   ✔ segment trouvé: {len(segment)} noeuds")

            for j in range(len(segment) - 1):
                u, v = segment[j], segment[j + 1]
                traversed_edges.add((u, v))
                traversed_edges.add((v, u))

            full_path_nodes.extend(segment[1:])
            current_node = poi["node"]

        except Exception as e:
            print(f"⚠️ shortest_path FAIL {current_node} -> {poi['node']} : {e}")

    print(f"📏 total nodes chemin POI: {len(full_path_nodes)}")

    update_status("Chemin construit entre les points sélectionnés", status_callback, 25)

    # ==========================================================
    # 5. CONVERSION + DISTANCE
    # ==========================================================
    full_path_coords = []
    total_distance = 0

    print("📐 Conversion noeuds -> coords")

    for i in range(len(full_path_nodes)):
        n = full_path_nodes[i]

        if n not in G.nodes:
            print(f"⚠️ node absent graphe: {n}")
            continue

        lon = G.nodes[n].get("lon")
        lat = G.nodes[n].get("lat")

        if lon is None or lat is None:
            if isinstance(n, tuple) and len(n) >= 2:
                lon, lat = n[0], n[1]
            else:
                print(f"⚠️ coords manquantes node={n}")
                continue

        full_path_coords.append((lon, lat))

        if i < len(full_path_nodes) - 1:
            n2 = full_path_nodes[i + 1]
            if G.has_edge(n, n2):
                d = G[n][n2].get("length", 0)
                total_distance += d
                print(f"   ➕ edge {n}->{n2} : {d:.1f}m")

    print(f"📏 distance totale POI chain: {total_distance:.1f}m")

    # ==========================================================
    # 6. CALCUL DISTANCE MAX + DISTANCE RESTANTE
    # ==========================================================
    update_status("Calcul de la distance maximale théorique", status_callback, 35)
    
    # Récupérer le nom massif cleané pour les fichiers
    from hello.management.commands.utils import slugify
    massif_clean = slugify(massif)
    
    # Calculer la distance maximale théorique
    max_distance_m, route_type = initialize_route_parameters(
        massif_name=massif,
        departure_time=departure_time,
        return_time=return_time,
        level=level,
        transit_route=None,  # On ne connaît pas encore le TC aller
        return_transit_seconds=None,
    )
    
    print(f"📏 Distance max théorique : {max_distance_m/1000:.1f} km")
    print(f"🗺️ Route type : {route_type}")
    
    # Distance restante après le chemin POI
    remaining_distance = max_distance_m - total_distance
    print(f"📏 Distance restante : {remaining_distance/1000:.1f} km")
    
    # Minimum 10km pour la recherche d'arrêts TC
    remaining_distance = max(remaining_distance, 10000)
    
    # ==========================================================
    # 7. RECHERCHE ARRÊTS TC ALLER (autour POI départ)
    # ==========================================================
    update_status("Recherche des arrêts de transport aller", status_callback, 40)
    
    first_poi = selected_pois[0]
    first_poi_coord = first_poi["node"]
    
    print(f"🚍 Recherche arrêts aller autour du POI {first_poi['id']} (node={first_poi_coord})")
    
    # Créer un sous-ensemble de stops_data avec les arrêts proches du premier POI
    nearby_stops_departure = {}
    first_poi_lat_lon = (first_poi["coord"][1], first_poi["coord"][0])  # (lat, lon)
    
    for stop_id, stop_info in stops_data.items():
        stop_coord = stop_info["node"]
        stop_lat_lon = (stop_coord[1], stop_coord[0])  # Convertir (lon, lat) en (lat, lon)
        dist = haversine(first_poi_lat_lon, stop_lat_lon)
        # Filtrer les arrêts dans un rayon de distance restante (minimum 10km)
        if dist <= remaining_distance:
            nearby_stops_departure[stop_id] = stop_info
    
    print(f"✅ {len(nearby_stops_departure)} arrêts trouvés autour du POI départ (rayon={remaining_distance/1000:.1f}km)")
    
    if not nearby_stops_departure:
        raise RuntimeError(f"Aucun arrêt de transport trouvé autour du POI {first_poi['id']}")
    
    # ==========================================================
    # 8. CALCUL TRAJET TC ALLER
    # ==========================================================
    update_status("Calcul du transport aller", status_callback, 45)
    
    print(f"📍 Calcul itinéraire TC de {address} vers le POI {first_poi['id']}")
    
    try:
        travel_go, departure_stop_id, departure_stop_info = get_best_transit_route(
            randomness=randomness,
            departure_time=departure_time,
            return_time=return_time,
            stops_data=nearby_stops_departure,
            address=address,
            transit_priority=transit_priority,
            hubs_entree_data=hubs_entree_data,
        )
        best_travel_go = travel_go
        print(f"✅ Itinéraire TC aller trouvé jusqu'à l'arrêt {departure_stop_id}")
    except Exception as e:
        print(f"⚠️ Erreur calcul itinéraire TC aller : {e}")
        raise RuntimeError(f"Impossible de calculer un itinéraire de transport aller vers le POI {first_poi['id']}: {e}")
    
    # Extraire le point d'arrivée du TC aller
    transit_arrival_lat = None
    transit_arrival_lon = None
    
    if travel_go:
        try:
            steps = travel_go["routes"][0]["legs"][0]["steps"]
            transit_steps = [s for s in steps if s.get("travelMode") == "TRANSIT"]

            if transit_steps:
                last_transit_step = transit_steps[-1]
                transit_arrival_lat = last_transit_step.get("endLocation", {}).get("latLng", {}).get("latitude")
                transit_arrival_lon = last_transit_step.get("endLocation", {}).get("latLng", {}).get("longitude")
        except Exception as e:
            print(f"⚠️ Erreur extraction point arrivée TC : {e}")
    
    if transit_arrival_lat is None or transit_arrival_lon is None:
        # Si on ne peut pas extraire le point d'arrivée, utiliser le stop_info
        transit_arrival_lon = departure_stop_info["node"][0]
        transit_arrival_lat = departure_stop_info["node"][1]
    
    print(f"📍 Point d'arrivée TC aller : ({transit_arrival_lat:.4f}, {transit_arrival_lon:.4f})")
    
    # ==========================================================
    # 9. RECHERCHE ARRÊTS TC RETOUR (autour POI arrivée)
    # ==========================================================
    update_status("Recherche des arrêts de transport retour", status_callback, 50)
    
    last_poi = selected_pois[-1]
    last_poi_coord = last_poi["node"]
    
    # Créer un stop_info fictif pour le dernier POI
    last_poi_stop_info = {
        "node": last_poi_coord,
        "properties": {}
    }
    
    # Pour le retour, on utilise le maximum entre la distance restante et 10km
    return_search_distance = max(remaining_distance, 10000)
    
    print(f"🚍 Recherche arrêts retour dans un rayon de {return_search_distance/1000:.1f} km autour du POI {last_poi['id']}")
    
    try:
        return_candidates = choose_return_stop(
            departure_stop_info=last_poi_stop_info,
            stops_data=stops_data,
            distance_max_m=return_search_distance,
            transit_priority=transit_priority,
        )
        print(f"✅ {len(return_candidates)} arrêts candidats trouvés pour le retour")
    except Exception as e:
        print(f"⚠️ Erreur recherche arrêts retour : {e}")
        raise RuntimeError(f"Impossible de trouver des arrêts de transport retour autour du POI {last_poi['id']}: {e}")
    
    # ==========================================================
    # 10. CALCUL TRAJET TC RETOUR
    # ==========================================================
    update_status("Calcul du transport retour", status_callback, 55)
    
    best_return_candidate = None
    best_travel_return = None
    best_return_duration = None
    
    for candidate in return_candidates:
        stop_id = candidate.get("stop_id")
        
        print(f"  ⬅️ Test arrêt retour {stop_id} (distance={candidate['dist']:.0f}m)")
        
        try:
            best_return_candidate, best_travel_return, best_return_duration = compute_return_transit(
                [candidate],
                return_time,
                address,
                stops_data=stops_data,
                departure_time=departure_time,
                status_callback=status_callback
            )
            print(f"    ✅ Itinéraire retour trouvé")
            break  # Prendre le premier qui marche
            
        except Exception as e:
            print(f"    ⚠️ Erreur itinéraire retour : {e}")
            time.sleep(0.05)
            continue
    
    if best_return_candidate is None:
        raise RuntimeError("Aucun itinéraire de transport en commun retour trouvé")
    
    print(f"✅ Arrêt retour sélectionné : {best_return_candidate.get('stop_id')}")
    
    # ==========================================================
    # 11. CONSTRUCTION DU CHEMIN FINAL
    # ==========================================================
    update_status("Construction du chemin final", status_callback, 60)
    
    # Le chemin final inclut:
    # - Point départ TC aller
    # - Trajet piéton TC→POI1
    # - Chemin entre POI (déjà calculé)
    # - Trajet piéton POIlast→TC retour
    
    def _node_coords(G, n):
        lon = G.nodes[n].get("lon")
        lat = G.nodes[n].get("lat")
        if lon is None or lat is None:
            if isinstance(n, tuple) and len(n) >= 2:
                return n[0], n[1]
            return None, None
        return lon, lat

    final_path = []

    # Trajet arrêt TC aller → premier POI
    departure_node = find_nearest_node(G, (transit_arrival_lat, transit_arrival_lon))
    print(f"🚶 Calcul chemin TC aller → POI1 : {departure_node} → {first_poi_coord}")
    try:
        walk_to_first_poi = shortest_path(G, departure_node, first_poi_coord, weight=penalized_weight)
        print(f"   chemin trouvé : {len(walk_to_first_poi)} nœuds")
        for j in range(len(walk_to_first_poi) - 1):
            u, v = walk_to_first_poi[j], walk_to_first_poi[j + 1]
            traversed_edges.add((u, v))
            traversed_edges.add((v, u))
        for n in walk_to_first_poi[:-1]:  # Exclure le dernier (= POI1, déjà dans full_path_coords)
            lon, lat = _node_coords(G, n)
            if lon is not None:
                final_path.append((lon, lat))
        print(f"   ✅ {len(walk_to_first_poi) - 1} points ajoutés")
    except Exception as e:
        print(f"⚠️ Chemin TC aller → POI1 impossible : {type(e).__name__}: {e}")

    # Chemin POI complet (premier au dernier)
    print(f"📍 Ajout chemin POI : {len(full_path_coords)} points")
    final_path.extend(full_path_coords)

    # Trajet dernier POI → arrêt TC retour
    return_stop_info = best_return_candidate.get("stop_info")
    return_node = find_nearest_node(G, (return_stop_info["node"][1], return_stop_info["node"][0]))
    print(f"🚶 Calcul chemin POI_last → TC retour : {last_poi_coord} → {return_node}")
    try:
        walk_from_last_poi = shortest_path(G, last_poi_coord, return_node, weight=penalized_weight)
        print(f"   chemin trouvé : {len(walk_from_last_poi)} nœuds")
        for n in walk_from_last_poi[1:]:  # Exclure le premier (= dernier POI, déjà dans full_path_coords)
            lon, lat = _node_coords(G, n)
            if lon is not None:
                final_path.append((lon, lat))
        print(f"   ✅ {len(walk_from_last_poi) - 1} points ajoutés")
    except Exception as e:
        print(f"⚠️ Chemin POI_last → TC retour impossible : {type(e).__name__}: {e}")

    # Point final : coordonnée exacte de l'arrêt TC retour
    return_stop_coord = (return_stop_info["node"][0], return_stop_info["node"][1])
    final_path.append(return_stop_coord)
    print(f"📍 Point TC retour ajouté : {return_stop_coord}")
    
    final_distance = total_distance  # Distance de marche pure (POI to POI)
    
    print(f"✅ Chemin final construit : {len(final_path)} points, distance marche={final_distance/1000:.1f} km")
    
    # ==========================================================
    # 12. RETOUR DU RÉSULTAT
    # ==========================================================
    update_status("Chemin avec POI calculé", status_callback, 65)
    
    result = {
        "path": final_path,
        "distance": final_distance,
        "travel_go": best_travel_go,
        "travel_return": best_travel_return,
        "route_type": route_type,
    }
    
    print(f"🎉 Résultat hiking_with_pois retourné avec succès")
    return result