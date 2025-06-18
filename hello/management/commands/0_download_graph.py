from django.core.management.base import BaseCommand
import osmnx as ox

class Command(BaseCommand):
    help = 'Download and save the pedestrian network for Parc naturel régional de Chartreuse'

    def handle(self, *args, **kwargs):
        self.stdout.write("Downloading pedestrian network for Parc naturel régional de Chartreuse...")
        G = ox.graph_from_place("Parc naturel régional de Chartreuse, France", network_type="walk")
        ox.save_graphml(G, filepath="data/chartreuse.graphml")
        self.stdout.write(self.style.SUCCESS("Graph saved to data/input/chartreuse.graphml"))
