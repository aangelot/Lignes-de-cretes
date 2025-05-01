import folium
import networkx as nx
import osmnx as ox

GRAPH_PATH = "data/chartreuse.graphml"

def compute_hike_path(start, end):
    G = ox.load_graphml(GRAPH_PATH)

    orig_node = ox.distance.nearest_nodes(G, X=start[1], Y=start[0])
    dest_node = ox.distance.nearest_nodes(G, X=end[1], Y=end[0])
    route = nx.shortest_path(G, orig_node, dest_node, weight="length")

    route_coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in route]

    # Create map centered at start
    m = folium.Map(location=start, zoom_start=14)

    # Draw the path
    folium.PolyLine(route_coords, color="blue", weight=5, opacity=0.7).add_to(m)

    # Optional: Add markers
    folium.Marker(location=start, popup="Start").add_to(m)
    folium.Marker(location=end, popup="End").add_to(m)

    return m