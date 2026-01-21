"""
Algorithme de recherche du meilleur chemin de randonnée.
Extraction et filtrage des POI près du tracé.
"""

import math
import random
from networkx import NetworkXNoPath, shortest_path
from shapely.geometry import LineString, Point
from .geotools import haversine, find_nearest_node, path_has_crossing
from .progress import add_progress_message


def best_hiking_path(start_coord, max_distance_m, G, poi_data, randomness=0.3, penalty_factor=100):
    """
    Algorithme frugal + aléatoire avec pénalisation des arêtes déjà parcourues.
    - randomise les scores par formule : (1 - r)*base + r*uniform(0,1)
    - sélectionne le meilleur POI et teste successivement suivant l'ordre décroissant
      si le meilleur n'est pas utilisable (pas de chemin, croisement, dépassement), on teste le suivant
    - si aucun POI accepté après 10 essais et croisement uniquement, on repêche le premier POI croisé
    - ajoute tous les POI à moins de 1000 m du segment au set des POI visités
    - marque toutes les arêtes parcourues
    Retour : (best_path_nodes, best_dist_m)
    """

    # --- Préparer POI avec randomisation ---
    pois = []
    for feat in poi_data.get("features", []):
        base_score = float(feat["properties"].get("score", 0.0))
        noisy_score = (1 - randomness) * base_score + randomness * random.uniform(0, 1)
        pois.append({
            "id": feat["properties"].get("titre"),
            "coord": tuple(feat["geometry"]["coordinates"]),  # (lon, lat)
            "score": noisy_score
        })

    print(f"Chargés {len(pois)} POI (randomness={randomness:.2f})")

    # --- Initialisation ---
    current_node = find_nearest_node(G, start_coord[::-1])
    best_path = [current_node]
    best_dist = 0.0
    visited_pois = set()
    visited_edges = set()
    max_candidate_trials = 10

    # fonction de coût dynamique avec pénalisation des arêtes déjà visitées
    def edge_cost(u, v, d):
        cost = d["length"] / (d.get("score", 0.0) + 1e-6)
        if (u, v) in visited_edges or (v, u) in visited_edges:
            cost *= penalty_factor
        return cost

    step = 0
    while best_dist <= max_distance_m - 5000:
        step += 1
        print(f"\n=== Étape {step} — distance actuelle {best_dist/1000:.2f} km ===")

        # --- Filtrer candidats non visités dans rayon ---
        radius_m = 5000
        candidates = [p for p in pois if p["id"] not in visited_pois and
                      haversine(current_node[::-1], p["coord"][::-1]) <= radius_m]
        if not candidates:
            radius_m *= 2
            candidates = [p for p in pois if p["id"] not in visited_pois and
                          haversine(current_node[::-1], p["coord"][::-1]) <= radius_m]
        if not candidates:
            print("Aucun POI accessible — fin de boucle")
            break

        # --- Trier par score ---
        candidates_sorted = sorted(candidates, key=lambda p: p["score"], reverse=True)

        accepted = False
        trials = 0
        first_crossed_poi = None
        all_over_budget = True

        for poi in candidates_sorted:
            if trials >= max_candidate_trials:
                print(f"Limite de {max_candidate_trials} essais atteinte pour cette étape.")
                break
            trials += 1

            print(f"Essai #{trials} pour POI '{poi['id']}' (score bruité={poi['score']:.4f})")
            poi_node = find_nearest_node(G, poi["coord"][::-1])

            try:
                path_nodes = shortest_path(G, current_node, poi_node, weight=edge_cost)
            except NetworkXNoPath:
                print(f"  - Pas de chemin vers {poi['id']} (NetworkXNoPath). On essaie le suivant.")
                visited_pois.add(poi["id"])
                continue
            except Exception as e:
                print(f"  - Erreur lors du calcul du chemin vers {poi['id']}: {e}. On essaie le suivant.")
                continue

            # --- Calcul distance réelle du segment ---
            seg_len = 0.0
            bad_length = False
            for u, v in zip(path_nodes[:-1], path_nodes[1:]):
                if "length" not in G[u][v]:
                    print(f"  - Avertissement : l'arête ({u},{v}) n'a pas d'attribut 'length'. Rejet du POI.")
                    bad_length = True
                    break
                seg_len += G[u][v]["length"]
            if bad_length:
                continue

            if best_dist + seg_len > max_distance_m:
                print(f"  - Le segment vers {poi['id']} dépasse le budget restant. On essaie le suivant.")
                continue
            else:
                all_over_budget = False

            # --- Vérification croisement ---
            crosses = path_has_crossing(best_path, path_nodes)
            if crosses:
                print(f"  - Rejeté: le segment vers {poi['id']} croise le chemin existant.")
                if first_crossed_poi is None:
                    first_crossed_poi = (poi, path_nodes, seg_len)
                continue

            # --- Acceptation normale ---
            accepted = True
            best_path.extend(path_nodes[1:])
            best_dist += seg_len
            current_node = path_nodes[-1]
            visited_pois.add(poi["id"])
            
            # Message de progression : POI sélectionné
            add_progress_message(f"Prochaine étape : {poi['id']} • Distance en cours : {best_dist/1000:.1f} km")

            # --- Ajouter POI proches du segment et marquer arêtes ---
            if len(path_nodes) >= 2:
                line_geom = LineString(path_nodes)
                for other_poi in pois:
                    if other_poi["id"] not in visited_pois:
                        pt = Point(other_poi["coord"])
                        if line_geom.distance(pt) <= 1000 / 111320:  # m -> degrés approx
                            visited_pois.add(other_poi["id"])
            for u, v in zip(path_nodes[:-1], path_nodes[1:]):
                visited_edges.add((u, v))
            break

        # --- Repêchage POI croisé ---
        if not accepted and first_crossed_poi is not None:
            poi, path_nodes, seg_len = first_crossed_poi
            print(f"⚠ Aucun POI accepté après {max_candidate_trials} essais ; on reprend malgré croisement : {poi['id']}")
            accepted = True
            best_path.extend(path_nodes[1:])
            best_dist += seg_len
            current_node = path_nodes[-1]
            visited_pois.add(poi["id"])

            # Ajouter POI proches et marquer arêtes
            if len(path_nodes) >= 2:
                line_geom = LineString(path_nodes)
                for other_poi in pois:
                    if other_poi["id"] not in visited_pois:
                        pt = Point(other_poi["coord"])
                        if line_geom.distance(pt) <= 1000 / 111320:
                            visited_pois.add(other_poi["id"])
                            print(f"    - POI ajouté par proximité <1000m : {other_poi['id']}")
            for u, v in zip(path_nodes[:-1], path_nodes[1:]):
                visited_edges.add((u, v))

        # --- Mode secours première étape ---
        if step == 1 and not accepted:
            print("⚠ Aucun POI accepté à la première étape. Activation du mode secours.")
            for poi in candidates_sorted:
                poi_node = find_nearest_node(G, poi["coord"][::-1])
                try:
                    path_nodes = shortest_path(G, current_node, poi_node)
                except:
                    continue

                seg_len = sum(G[u][v].get("length", 0) for u, v in zip(path_nodes[:-1], path_nodes[1:]))

                if best_dist + seg_len <= max_distance_m:
                    print(f"  + Secours: POI '{poi['id']}' accepté.")
                    accepted = True
                    best_path.extend(path_nodes[1:])
                    best_dist += seg_len
                    current_node = path_nodes[-1]
                    visited_pois.add(poi["id"])

                    # Ajouter POI proches et marquer arêtes
                    if len(path_nodes) >= 2:
                        line_geom = LineString(path_nodes)
                        for other_poi in pois:
                            if other_poi["id"] not in visited_pois:
                                pt = Point(other_poi["coord"])
                                if line_geom.distance(pt) <= 1000 / 111320:
                                    visited_pois.add(other_poi["id"])
                                    print(f"    - POI ajouté par proximité <1000m : {other_poi['id']}")
                    for u, v in zip(path_nodes[:-1], path_nodes[1:]):
                        visited_edges.add((u, v))
                    break

            if not accepted:
                print("🚫 Mode secours impossible: aucun POI atteignable dans le budget.")
            break  # sortir après première étape

        # --- Sortir si tous les POI dépassent la distance max ---
        if not accepted and all_over_budget:
            print("🚫 Tous les POI dépassent la distance max — arrêt de la recherche.")
            break

    print("\n=== Recherche terminée ===")
    print(f"Distance finale: {best_dist/1000:.2f} km, points: {len(best_path)}, POI visités: {len(visited_pois)}")
    return best_path, best_dist


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
