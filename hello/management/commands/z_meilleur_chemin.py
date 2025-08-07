from django.core.management.base import BaseCommand
from hello.services.trouver_chemin import compute_best_route, save_geojson

class Command(BaseCommand):
    help = "Calcule le meilleur chemin optimisé"

    def add_arguments(self, parser):
        parser.add_argument('--city', type=str, default='Lyon')
        parser.add_argument('--massif', type=str, default='Chartreuse')
        parser.add_argument('--level', type=str, choices=['debutant', 'intermediaire', 'avance', 'expert'], default='debutant')

    def handle(self, *args, **options):
        city = options['city']
        massif = options['massif']
        level = options['level']

        self.stdout.write(self.style.SUCCESS(f"Calcul du meilleur chemin pour city={city}, massif={massif}, niveau={level}"))

        geojson = compute_best_route(level=level, city=city, massif=massif)
        save_geojson(geojson)

        self.stdout.write(self.style.SUCCESS("✅ Itinéraire optimisé généré avec succès"))
