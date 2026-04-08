"""
Algorithme de recherche du meilleur chemin de randonnée.
Extraction et filtrage des POI près du tracé.
"""

import math
import random
from networkx import NetworkXNoPath, shortest_path
from shapely.geometry import LineString, Point
from .geotools import haversine, find_nearest_node, path_has_crossing
from hello.constants import HIKE_DISTANCE_CONSUMPTION_THRESHOLD
from hello.management.commands.utils import slugify

def best_hiking_crossing(
    start_coord,
    end_coord,
    max_distance_m,
    G,
    poi_data,
    randomness=0.3,
):
    """
    Construction d'une traversée maximisant la distance et le nombre de POI de qualité,
    tout en maintenant un trajet harmonieux le long de la ligne droite.
    """

    print(f"🔍 Recherche chemin rando optimisé: départ={start_coord}, arrivée={end_coord}, distance_max={max_distance_m/1000:.1f}km")

    # 1. Créer la ligne droite et un buffer latéral pour explorer le massif
    direct_line = LineString([start_coord, end_coord])
    buffer_geom = direct_line.buffer(0.09, cap_style=2)  # Buffer de 10km de largeur, caps plats pour éviter l'extension longitudinale

    print(f"📏 Ligne directe: {direct_line.length*111:.1f}km, buffer de 10km créé")

    # 2. Collecter tous les POI dans le buffer, triés par score décroissant
    all_pois = []
    for feat in poi_data.get("features", []):
        poi_point = Point(feat["geometry"]["coordinates"])
        if buffer_geom.contains(poi_point):
            base_score = float(feat["properties"].get("score", 0.0))
            noisy_score = (1 - randomness) * base_score + randomness * random.uniform(0, 1)
            all_pois.append({
                "id": feat["properties"].get("titre"),
                "coord": tuple(feat["geometry"]["coordinates"]),
                "score": noisy_score,
                "properties": feat["properties"]
            })

    # Trier par score décroissant
    all_pois.sort(key=lambda x: x["score"], reverse=True)

    # Limiter à 5 POI max pour gérer les calculs de shortest_path efficacement
    # avec un buffer aussi large (10km). Cela garde les meilleurs scores.
    all_pois = all_pois[:5]

    top_pois = [f'{p["id"]}({p["score"]:.2f})' for p in all_pois[:5]]
    print(f"📍 {len(all_pois)} POI dans le buffer (top 5), meilleurs scores: {top_pois}")

    if not all_pois:
        print("⚠️ Aucun POI trouvé, trajet direct")
        return _direct_path_fallback(start_coord, end_coord, G)

    # 3. Sélectionner le meilleur sous-ensemble de POI et construire le chemin
    selected_pois, final_path = _build_optimal_poi_path(
        start_coord, end_coord, all_pois, max_distance_m, G
    )

    if not selected_pois:
        print("⚠️ Aucun POI sélectionnable, trajet direct")
        return _direct_path_fallback(start_coord, end_coord, G)

    print(f"🏆 {len(selected_pois)} POI sélectionnés pour trajet harmonieux: {[p['id'] for p in selected_pois]}")

    # 4. Calculer la longueur du chemin
    try:
        final_len = sum(G[u][v]["length"] for u, v in zip(final_path[:-1], final_path[1:]))

        print(f"✅ Chemin optimisé: {final_len/1000:.1f}km ({final_len/max_distance_m*100:.1f}% de max)")
        print(f"   Score total POI: {sum(p['score'] for p in selected_pois):.2f}")

        return final_path, final_len

    except Exception as e:
        print(f"❌ Erreur construction chemin: {e}, fallback trajet direct")
        return _direct_path_fallback(start_coord, end_coord, G)


def _build_optimal_poi_path(start_coord, end_coord, all_pois, max_distance_m, G):
    """
    Sélectionne la séquence optimale de POI et construit le chemin complet,
    tout en respectant la distance max et la cohérence du trajet.
    Retourne la liste des POI sélectionnés et le chemin complet.
    
    OPTIMISATION : Pénalise fortement les arêtes déjà parcourues pour éviter les aller-retours.
    """
    start_node = find_nearest_node(G, start_coord[::-1])
    end_node = find_nearest_node(G, end_coord[::-1])

    def path_len(path_nodes):
        return sum(G[u][v]["length"] for u, v in zip(path_nodes[:-1], path_nodes[1:]))

    # Sauvegarder les poids originaux des arêtes (pour éviter une modification permanente)
    original_weights = {}
    for u, v, data in G.edges(data=True):
        original_weights[(u, v)] = data.get("length", 1.0)
        # Créer une clé symétrique pour les arêtes non-dirigées
        original_weights[(v, u)] = data.get("length", 1.0)
    
    # Tracker les arêtes déjà utilisées (et leur fréquence de réutilisation)
    used_edges = {}

    # Distance directe pour référence
    try:
        direct_path = shortest_path(G, start_node, end_node, weight="length")
        direct_len = path_len(direct_path)
    except NetworkXNoPath:
        return [], []

    # Projeter chaque POI sur la ligne droite pour avoir un ordre naturel
    direct_line = LineString([start_coord, end_coord])

    def project_on_line(coord):
        """Projette un point sur la ligne et retourne la distance depuis le départ"""
        point = Point(coord)
        # Distance le long de la ligne (approximation)
        return direct_line.project(point)

    # Ajouter la projection à chaque POI
    for poi in all_pois:
        poi["projection"] = project_on_line(poi["coord"])

    # Trier par projection (ordre naturel le long de la ligne)
    pois_by_projection = sorted(all_pois, key=lambda x: x["projection"])

    # Approche gloutonne: sélectionner les meilleurs POI dans l'ordre,
    # en sautant ceux qui feraient dépasser la distance
    selected = []
    partial_path = [start_node]
    current_pos = start_coord
    current_node = start_node
    remaining_distance = max_distance_m
    
    # Debug: tracker les POI considérés
    considered = 0
    too_far = 0
    inaccessible = 0
    
    # Pénalité pour les arêtes réutilisées (multiplicateur de coût)
    REUSE_PENALTY_MULTIPLIER = 5.0

    for poi in pois_by_projection:
        
        considered += 1
        poi_node = find_nearest_node(G, poi["coord"][::-1])

        try:
            # Distance de la position actuelle au POI
            segment_path = shortest_path(G, current_node, poi_node, weight="length")
            segment_len = path_len(segment_path)

            if segment_len > remaining_distance:
                too_far += 1
                continue  # Trop loin, passer au suivant

            # Ajouter ce POI
            selected.append(poi)
            
            # Marquer les arêtes de ce segment comme utilisées et augmenter leur poids
            for i in range(len(segment_path) - 1):
                u, v = segment_path[i], segment_path[i + 1]
                edge_key = (u, v) if (u, v) in original_weights else (v, u)
                
                # Tracker le nombre de fois que cette arête a été utilisée
                reuse_count = used_edges.get(edge_key, 0)
                used_edges[edge_key] = reuse_count + 1
                
                # Augmenter le poids de l'arête de manière exponentielle avec la réutilisation
                # Pour fortement dissuader le backtracking
                new_weight = original_weights[edge_key] * (1 + REUSE_PENALTY_MULTIPLIER * (reuse_count + 1))
                
                # Mettre à jour les deux directions de l'arête (graphe non-dirigé)
                if G.has_edge(u, v):
                    G[u][v]["length"] = new_weight
                if G.has_edge(v, u):
                    G[v][u]["length"] = new_weight
            
            partial_path.extend(segment_path[1:])  # Étendre le chemin partiel
            current_node = poi_node
            remaining_distance -= segment_len

        except NetworkXNoPath:
            inaccessible += 1
            continue  # POI inaccessible, passer
    
    if considered > 0:
        print(f"   Sélection: {considered} POI considérés, {len(selected)} sélectionnés, {too_far} trop loin, {inaccessible} inaccessibles")

    # Vérifier qu'on peut atteindre l'arrivée depuis le dernier POI et construire le chemin complet
    if selected:
        try:
            final_segment = shortest_path(G, current_node, end_node, weight="length")
            final_len = path_len(final_segment)

            if final_len > remaining_distance:
                # Retirer le dernier POI si ça empêche d'atteindre l'arrivée
                if len(selected) > 1:
                    removed = selected.pop()
                    print(f"⚠️ POI '{removed['id']}' retiré pour atteindre l'arrivée")
                    # Recalculer le chemin partiel sans le dernier POI
                    partial_path = [start_node]
                    for p in selected:
                        poi_node = find_nearest_node(G, p["coord"][::-1])
                        segment = shortest_path(G, partial_path[-1], poi_node, weight="length")
                        partial_path.extend(segment[1:])
                    # Construire le chemin complet avec le nouveau final_segment
                    final_segment = shortest_path(G, partial_path[-1], end_node, weight="length")
                    final_path = partial_path + final_segment[1:]
                else:
                    # Si un seul POI et qu'on ne peut pas atteindre l'arrivée, le retirer
                    selected = []
                    final_path = []
            else:
                # Construire le chemin complet
                final_path = partial_path + final_segment[1:]
        except NetworkXNoPath:
            # Ne peut pas atteindre l'arrivée, retirer le dernier POI
            if selected:
                removed = selected.pop()
                print(f"⚠️ POI '{removed['id']}' retiré (arrivée inaccessible)")
                # Recalculer le chemin partiel sans le dernier POI
                partial_path = [start_node]
                for p in selected:
                    poi_node = find_nearest_node(G, p["coord"][::-1])
                    segment = shortest_path(G, partial_path[-1], poi_node, weight="length")
                    partial_path.extend(segment[1:])
                # Construire le chemin complet
                try:
                    final_segment = shortest_path(G, partial_path[-1], end_node, weight="length")
                    final_path = partial_path + final_segment[1:]
                except NetworkXNoPath:
                    final_path = []
            else:
                final_path = []
    else:
        final_path = []
    
    # Restaurer les poids originaux du graphe
    for u, v, data in G.edges(data=True):
        if (u, v) in original_weights:
            G[u][v]["length"] = original_weights[(u, v)]

    return selected, final_path



def _direct_path_fallback(start_coord, end_coord, G):
    """Fallback vers le trajet direct le plus court"""
    start_node = find_nearest_node(G, start_coord[::-1])
    end_node = find_nearest_node(G, end_coord[::-1])

    try:
        direct_path = shortest_path(G, start_node, end_node, weight="length")
        direct_len = sum(G[u][v]["length"] for u, v in zip(direct_path[:-1], direct_path[1:]))
        print(f"➡️ Trajet direct: {direct_len/1000:.1f}km")
        return direct_path, direct_len
    except NetworkXNoPath:
        print("❌ Aucun chemin possible")
        return [], 0


def best_hiking_massif_tour(
    start_coord,
    max_distance_m,
    G,
    poi_data,
    stops_data,
    randomness=0.3,
    massif_name="Chartreuse",
):
    """
    Fonction pour les randonnées en tour de massif.
    Logique : partir du point de départ et faire un tour progressif du massif
    en visitant les meilleurs POI dans la bonne direction.
    
    Étapes :
    1. Déterminer le sens de rotation (horaire/anti-horaire) pour un trajet cohérent
    2. À chaque étape, trouver le meilleur POI dans les 5km dans la "bonne direction"
    3. Calculer le trajet pour y aller
    4. Continuer jusqu'à ce qu'il reste moins de 10km de distance max
    5. Utiliser choose_return_stop pour trouver l'arrêt final dans les 10km restants
    """
    
    print(f"🔄 Recherche chemin rando en tour de massif: départ={start_coord}, max_distance={max_distance_m/1000:.1f}km")
    
    # 1. Déterminer le centre du massif (approximation)
    massif_center = _get_massif_center(massif_name)
    print(f"📍 Centre du massif '{massif_name}' estimé: {massif_center}")
    
    # 2. Choisir aléatoirement le sens de rotation pour varier les tours
    rotation_direction = _determine_rotation_direction(start_coord, massif_center)
    print(f"🔄 Sens de rotation choisi aléatoirement: {'horaire' if rotation_direction == 'clockwise' else 'anti-horaire'}")
    
    # 3. Initialisation
    current_coord = start_coord
    current_node = find_nearest_node(G, start_coord[::-1])
    remaining_distance = max_distance_m
    path_segments = [current_node]
    path_coords = [start_coord]  # Liste des coordonnées du chemin construit
    visited_pois = set()
    
    # Sauvegarder les poids originaux pour la pénalité anti-retour
    original_weights = {}
    for u, v, data in G.edges(data=True):
        original_weights[(u, v)] = data.get("length", 1.0)
        original_weights[(v, u)] = data.get("length", 1.0)
    
    used_edges = {}
    REUSE_PENALTY_MULTIPLIER = 5.0
    
    try:
        while remaining_distance > 10000:  # 10km
            
            # Trouver les POI candidats dans la bonne direction
            # Essayer d'abord avec 5km, puis élargir à 10km si aucun POI trouvé
            candidate_pois = _find_pois_in_direction(
                current_coord, 
                massif_center, 
                poi_data, 
                max_distance=5000,  # 5km
                rotation_direction=rotation_direction,
                visited_pois=visited_pois,
                path_coords=path_coords
            )
            
            if not candidate_pois:
                print(f"⚠️ Aucun POI trouvé dans 5km, élargissement à 30km")
                candidate_pois = _find_pois_in_direction(
                    current_coord, 
                    massif_center, 
                    poi_data, 
                    max_distance=30000,  # 30km
                    rotation_direction=rotation_direction,
                    visited_pois=visited_pois,
                    path_coords=path_coords
                )

            if not candidate_pois:
                print(f"⚠️ Aucun POI trouvé dans 30km dans la bonne direction, élargissement à 30km toutes directions")
                candidate_pois = _find_pois_in_radius(
                    current_coord,
                    poi_data,
                    max_distance=30000,
                    visited_pois=visited_pois,
                    path_coords=path_coords
                )

            if not candidate_pois:
                print(f"⚠️ Aucun POI trouvé, arrêt du tour (distance restante: {remaining_distance/1000:.1f}km)")
                break
            
            # Sélectionner le meilleur POI
            best_poi = _select_best_poi_in_sector(candidate_pois, randomness)
            poi_coord = best_poi["coord"]
            poi_node = find_nearest_node(G, poi_coord[::-1])
            
            print(f"🎯 POI sélectionné: {best_poi['id']} (score={best_poi['score']:.2f}) à {haversine(current_coord, poi_coord):.0f}m")
            
            # Calculer le trajet vers ce POI
            segment_path = shortest_path(G, current_node, poi_node, weight="length")
            segment_len = sum(G[u][v]["length"] for u, v in zip(segment_path[:-1], segment_path[1:]))
            
            if segment_len > remaining_distance:
                print(f"⚠️ Trajet vers POI trop long ({segment_len/1000:.1f}km > {remaining_distance/1000:.1f}km restants)")
                break
            
            # Marquer les arêtes comme utilisées (pénalité anti-retour)
            for i in range(len(segment_path) - 1):
                u, v = segment_path[i], segment_path[i + 1]
                edge_key = (u, v) if (u, v) in original_weights else (v, u)
                
                reuse_count = used_edges.get(edge_key, 0)
                used_edges[edge_key] = reuse_count + 1
                
                new_weight = original_weights[edge_key] * (1 + REUSE_PENALTY_MULTIPLIER * (reuse_count + 1))
                
                if G.has_edge(u, v):
                    G[u][v]["length"] = new_weight
                if G.has_edge(v, u):
                    G[v][u]["length"] = new_weight
            
            # Ajouter le segment au chemin
            path_segments.extend(segment_path[1:])
            
            # Ajouter les coordonnées du segment au chemin construit
            for node in segment_path[1:]:  # segment_path[0] est déjà dans path_coords
                if node in G.nodes and "lon" in G.nodes[node] and "lat" in G.nodes[node]:
                    node_coord = (G.nodes[node]["lon"], G.nodes[node]["lat"])
                    path_coords.append(node_coord)
            
            current_node = poi_node
            current_coord = poi_coord
            remaining_distance -= segment_len
            visited_pois.add(best_poi["id"])
            
            print(f"✅ Segment ajouté: {segment_len/1000:.1f}km, distance restante: {remaining_distance/1000:.1f}km")
        
        # Restaurer les poids originaux avant le calcul final
        for u, v, data in G.edges(data=True):
            if (u, v) in original_weights:
                G[u][v]["length"] = original_weights[(u, v)]
        
        # 4. Phase finale : plus de POI ou distance épuisée
        total_distance = sum(G[u][v]["length"] for u, v in zip(path_segments[:-1], path_segments[1:]))
        print(f"🏁 Fin du tour de massif: {len(path_segments)-1} segments, distance totale: {total_distance/1000:.1f}km")
        return path_segments, total_distance
        
    except NetworkXNoPath:
        print("❌ Chemin impossible trouvé")
        return [], 0


def best_hiking_loop(
    start_coord,
    max_distance_m,
    G,
    poi_data,
    randomness=0.3,
    massif_name="Chartreuse",
):
    """
    Fonction pour les randonnées en boucle (départ = arrivée).
    Logique : créer un point fictif à distance_max/2 en direction du centre du massif,
    puis calculer un trajet aller avec POI et un trajet retour avec POI différents.
    
    Étapes :
    1. Obtenir le centre du massif
    2. Créer un point fictif à distance_max/2 en direction du centre
    3. Calculer trajet aller vers le point fictif avec POI
    4. Calculer trajet retour du point fictif vers le départ avec POI différents
    5. Retourner le chemin complet (aller + retour)
    """
    
    print(f"🔁 Recherche chemin rando en boucle: départ={start_coord}, max_distance={max_distance_m/1000:.1f}km")
    
    # 1. Obtenir le centre du massif
    massif_center = _get_massif_center(massif_name)
    print(f"📍 Centre du massif '{massif_name}' estimé: {massif_center}")
    
    # 2. Créer un point fictif à distance_max/2 en direction du centre
    half_distance_m = max_distance_m / 2
    
    # Calculer l'angle et la distance vers le centre
    start_lon, start_lat = start_coord
    center_lon, center_lat = massif_center
    
    dx = center_lon - start_lon
    dy = center_lat - start_lat
    angle_to_center = math.atan2(dy, dx)
    
    # Convertir distance en degrés (approximation: 1 degré ≈ 111 km)
    distance_in_degrees = half_distance_m / (111000)
    
    fictitious_lon = start_lon + distance_in_degrees * math.cos(angle_to_center)
    fictitious_lat = start_lat + distance_in_degrees * math.sin(angle_to_center)
    fictitious_point = (fictitious_lon, fictitious_lat)
    
    print(f"🎯 Point fictif créé à {haversine(start_coord, fictitious_point):.0f}m (distance max/2)")
    
    # 3. Calculer trajet aller du départ vers le point fictif
    try:
        path_go, dist_go = best_hiking_crossing(
            start_coord=start_coord,
            end_coord=fictitious_point,
            max_distance_m=max_distance_m,  # On utilise la distance max complète pour la flexibilité
            G=G,
            poi_data=poi_data,
            randomness=randomness,
        )
    except Exception as e:
        print(f"❌ Échec trajet aller en boucle: {e}")
        return [], 0
    
    if not path_go:
        print("❌ Aucun chemin aller trouvé pour la boucle")
        return [], 0
    
    # 4. Calculer trajet retour du point fictif vers le départ
    # Utiliser la distance restante (max_distance - distance_aller)
    remaining_distance = max_distance_m - dist_go
    
    try:
        path_return, dist_return = best_hiking_crossing(
            start_coord=fictitious_point,
            end_coord=start_coord,
            max_distance_m=remaining_distance,
            G=G,
            poi_data=poi_data,
            randomness=randomness,
        )
    except Exception as e:
        print(f"❌ Échec trajet retour en boucle: {e}")
        return [], 0
    
    if not path_return:
        print("❌ Aucun chemin retour trouvé pour la boucle")
        return [], 0
    
    # 5. Combiner les deux trajets
    # Path est une liste de nœuds du graphe
    # On concatène en omettant le premier nœud du retour (qui est le dernier du aller)
    complete_path = path_go + path_return[1:]
    total_distance = dist_go + dist_return
    
    print(f"✅ Boucle complète: aller={dist_go/1000:.1f}km + retour={dist_return/1000:.1f}km = {total_distance/1000:.1f}km")
    
    return complete_path, total_distance


def _is_poi_too_close_to_path(poi_coord, path_coords, max_distance_m=1000):
    """
    Vérifie si un POI est à moins de max_distance_m mètres du chemin déjà construit.
    
    Args:
        poi_coord: tuple (lon, lat) du POI
        path_coords: liste de tuples (lon, lat) du chemin construit
        max_distance_m: distance seuil en mètres
    
    Returns:
        bool: True si le POI est trop proche du chemin
    """
    for path_coord in path_coords:
        if haversine(poi_coord, path_coord) < max_distance_m:
            return True
    return False


def _get_massif_center(massif_name="Chartreuse"):
    """
    Détermine le centre approximatif du massif spécifié.
    Lit les données depuis massifs_coord_max_with_centers.geojson
    Utilise slugify pour normaliser le nom du massif.
    """
    import json
    import os

    geojson_path = "data/input/massifs_coord_max_with_centers.geojson"
    
    # Normaliser le nom du massif avec slugify
    massif_slug = slugify(massif_name)

    try:
        with open(geojson_path, 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)

        # Rechercher le massif spécifié (en utilisant le nom slugifié)
        for feature in geojson_data.get('features', []):
            properties = feature.get('properties', {})
            # Comparer avec le nom original ou slugifié dans le fichier
            massif_in_file = properties.get('nom_pnr', '')
            if slugify(massif_in_file) == massif_slug:
                centre = properties.get('centre')
                if centre:
                    return (centre['longitude'], centre['latitude'])

        # Si le massif n'est pas trouvé, retourner une valeur par défaut (Chartreuse)
        print(f"⚠️ Massif '{massif_name}' (slug: '{massif_slug}') non trouvé, utilisation de Chartreuse par défaut")
        return (5.79889015, 45.379814100000004)  # Centre de Chartreuse

    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"⚠️ Erreur lors de la lecture du fichier {geojson_path}: {e}")
        print("Utilisation de Chartreuse par défaut")
        return (5.79889015, 45.379814100000004)  # Centre de Chartreuse


def _determine_rotation_direction(start_coord, massif_center):
    """
    Choisit aléatoirement le sens de rotation (horaire/anti-horaire).
    Cela permet de varier les résultats sur des tours de massif successifs.
    """
    return random.choice(["clockwise", "counterclockwise"])


def _find_pois_in_direction(current_coord, massif_center, poi_data, max_distance=5000, 
                           rotation_direction="clockwise", visited_pois=None, path_coords=None):
    """
    Trouve les POI dans la 'bonne direction' selon le sens de rotation.
    
    Logique :
    - Calcule l'angle entre le centre et la position actuelle
    - Définit un secteur angulaire devant (135° dans le sens de rotation)
    - Filtre les POI dans ce secteur et à distance max
    - Exclut les POI trop proches du chemin déjà construit
    """
    if visited_pois is None:
        visited_pois = set()
    if path_coords is None:
        path_coords = []
    
    current_lon, current_lat = current_coord
    center_lon, center_lat = massif_center
    
    # Calculer l'angle actuel par rapport au centre (en radians)
    dx = current_lon - center_lon
    dy = current_lat - center_lat
    current_angle = math.atan2(dy, dx)  # Angle en radians [-pi, pi]
    
    # Définir le secteur angulaire devant (135° = 3*pi/4 radians pour une recherche plus large)
    sector_angle = 3 * math.pi / 4  # 135 degrés
    
    if rotation_direction == "clockwise":
        # Secteur : [current_angle, current_angle + sector_angle]
        min_angle = current_angle
        max_angle = current_angle + sector_angle
    else:
        # Secteur : [current_angle - sector_angle, current_angle]
        min_angle = current_angle - sector_angle
        max_angle = current_angle
    
    candidates = []
    
    for feat in poi_data.get("features", []):
        poi_id = feat["properties"].get("titre")
        if poi_id in visited_pois:
            continue
            
        poi_coord = tuple(feat["geometry"]["coordinates"])
        
        # Vérifier si le POI est trop proche du chemin déjà construit
        if _is_poi_too_close_to_path(poi_coord, path_coords, max_distance_m=2000):
            continue
        
        poi_lon, poi_lat = poi_coord
        
        # Distance au point actuel
        dist = haversine(current_coord, poi_coord)
        if dist > max_distance or dist < 100:  # Min 100m pour éviter les POI trop proches
            continue
        
        # Calculer l'angle du POI par rapport au centre
        dx_poi = poi_lon - center_lon
        dy_poi = poi_lat - center_lat
        poi_angle = math.atan2(dy_poi, dx_poi)
        
        # Normaliser les angles pour gérer les discontinuités à ±pi
        def normalize_angle(angle):
            while angle > math.pi:
                angle -= 2 * math.pi
            while angle < -math.pi:
                angle += 2 * math.pi
            return angle
        
        poi_angle_norm = normalize_angle(poi_angle)
        min_angle_norm = normalize_angle(min_angle)
        max_angle_norm = normalize_angle(max_angle)
        
        # Vérifier si le POI est dans le secteur angulaire
        if rotation_direction == "clockwise":
            # Gestion du wrap-around pour le sens horaire
            if min_angle_norm <= max_angle_norm:
                in_sector = min_angle_norm <= poi_angle_norm <= max_angle_norm
            else:
                in_sector = poi_angle_norm >= min_angle_norm or poi_angle_norm <= max_angle_norm
        else:
            # Gestion du wrap-around pour le sens anti-horaire
            if min_angle_norm <= max_angle_norm:
                in_sector = min_angle_norm <= poi_angle_norm <= max_angle_norm
            else:
                in_sector = poi_angle_norm >= min_angle_norm or poi_angle_norm <= max_angle_norm
        
        if in_sector:
            base_score = float(feat["properties"].get("score", 0.0))
            candidates.append({
                "id": poi_id,
                "coord": poi_coord,
                "score": base_score,
                "distance": dist,
                "angle": poi_angle_norm
            })
    
    return candidates


def _find_pois_in_radius(current_coord, poi_data, max_distance=10000, visited_pois=None, path_coords=None):
    """
    Trouve des POI dans un rayon donné sans contrainte de direction.
    Exclut les POI trop proches du chemin déjà construit.
    """
    if visited_pois is None:
        visited_pois = set()
    if path_coords is None:
        path_coords = []

    current_lon, current_lat = current_coord
    candidates = []

    for feat in poi_data.get("features", []):
        poi_id = feat["properties"].get("titre")
        if poi_id in visited_pois:
            continue

        poi_coord = tuple(feat["geometry"]["coordinates"])
        
        # Vérifier si le POI est trop proche du chemin déjà construit
        if _is_poi_too_close_to_path(poi_coord, path_coords, max_distance_m=1000):
            continue
        
        dist = haversine(current_coord, poi_coord)
        if dist > max_distance or dist < 100:
            continue

        base_score = float(feat["properties"].get("score", 0.0))
        candidates.append({
            "id": poi_id,
            "coord": poi_coord,
            "score": base_score,
            "distance": dist,
        })

    return candidates


def _select_best_poi_in_sector(candidate_pois, randomness=0.3):
    """
    Sélectionne le meilleur POI parmi les candidats dans le secteur.
    Applique un bruit aléatoire et privilégie les POI proches.
    """
    if not candidate_pois:
        return None
    
    # Calculer un score composite : score_base + bonus proximité + bruit
    scored_pois = []
    for poi in candidate_pois:
        # Score de base
        base_score = poi["score"]
        
        # Bonus pour proximité (max 0.3 points pour les POI très proches)
        proximity_bonus = max(0, (5000 - poi["distance"]) / 5000) * 0.3
        
        # Bruit aléatoire
        noise = random.uniform(-randomness, randomness)
        
        final_score = base_score + proximity_bonus + noise
        
        scored_pois.append({
            **poi,
            "final_score": final_score
        })
    
    # Sélectionner le meilleur
    best_poi = max(scored_pois, key=lambda x: x["final_score"])
    
    return best_poi


def extract_pois_near_path(path, poi_data, max_distance_m=200):
    """
    Extrait de `poi_data` les features (POI) dont la distance minimale
    au tracé `path` est inférieure ou égale à `max_distance_m` mètres.

    Args:
        path: liste de points [(lon, lat) ou [lon, lat, ele], ...] décrivant le tracé.
        poi_data: GeoJSON dict contenant une clé `features`.
        max_distance_m: distance seuil en mètres (défaut 200).

    Retourne:
        liste de features (dict) filtrées, conservant tous les attributs.
    """
    R = 6371000.0
    def to_xy(lon, lat, lat_ref):
        x = math.radians(lon) * math.cos(math.radians(lat_ref)) * R
        y = math.radians(lat) * R
        return (x, y)

    def point_segment_distance_m(pt_lonlat, a_lonlat, b_lonlat):
        plat, plon = pt_lonlat[1], pt_lonlat[0]
        alat, alon = a_lonlat[1], a_lonlat[0]
        blat, blon = b_lonlat[1], b_lonlat[0]
        lat_ref = (plat + alat + blat) / 3.0
        px, py = to_xy(plon, plat, lat_ref)
        ax, ay = to_xy(alon, alat, lat_ref)
        bx, by = to_xy(blon, blat, lat_ref)
        vx, vy = bx - ax, by - ay
        wx, wy = px - ax, py - ay
        vlen2 = vx*vx + vy*vy
        if vlen2 == 0:
            return math.hypot(px - ax, py - ay)
        t = (wx*vx + wy*vy) / vlen2
        t = max(0.0, min(1.0, t))
        projx = ax + t * vx
        projy = ay + t * vy
        return math.hypot(px - projx, py - projy)

    if not path or not poi_data or "features" not in poi_data:
        return []

    near_features = []
    for feat in poi_data.get("features", []):
        try:
            coords = feat.get("geometry", {}).get("coordinates")
            if not coords or len(coords) < 2:
                continue
            poi = (coords[0], coords[1])  # (lon, lat)
            min_d = float("inf")
            # parcourir segments
            if len(path) >= 2:
                for u, v in zip(path[:-1], path[1:]):
                    # u and v may be [lon,lat] or [lon,lat,ele]
                    ua = (u[0], u[1])
                    vb = (v[0], v[1])
                    d = point_segment_distance_m(poi, ua, vb)
                    if d < min_d:
                        min_d = d
                    if min_d <= max_distance_m:
                        break
            else:
                # path single point
                node = path[0]
                d_node = haversine((poi[1], poi[0]), (node[1], node[0]))
                min_d = min(min_d, d_node)

            if min_d <= max_distance_m:
                near_features.append(feat)
        except Exception:
            continue

    return near_features
