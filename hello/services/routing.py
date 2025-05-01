import osmnx as ox
import networkx as nx

GRAPH_PATH = "data/chartreuse.graphml"

def compute_hike_path(start, end):
    G = ox.load_graphml(GRAPH_PATH)

    # Find nearest nodes
    orig_node = ox.distance.nearest_nodes(G, X=start[1], Y=start[0])
    dest_node = ox.distance.nearest_nodes(G, X=end[1], Y=end[0])

    # Compute shortest path
    route = nx.shortest_path(G, orig_node, dest_node, weight="length")

    # Get route coordinates as [lat, lon] pairs
    route_coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in route]

    return route_coords

