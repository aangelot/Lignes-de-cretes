from django.core.management.base import BaseCommand
from hello.services.trouver_chemin import compute_best_route, save_geojson

class Command(BaseCommand):
    help = "Calcule le meilleur chemin optimisé"

    def add_arguments(self, parser):
        parser.add_argument('--city', type=str, default='Lyon')
        parser.add_argument(
            '--level',
            type=str,
            choices=['debutant', 'intermediaire', 'avance', 'expert'],
            default='debutant'
        )
        parser.add_argument(
            '--randomness',
            type=float,
            default=0.3,
            help="Valeur entre 0 et 1 pour l'aléatoire dans la sélection des points"
        )
        parser.add_argument(
            '--departure_datetime',
            type=str,
            help="Date et heure de départ au format ISO (ex: 2025-08-18T08:30)"
        )
        parser.add_argument(
            '--return_datetime',
            type=str,
            help="Date et heure de retour au format ISO (ex: 2025-08-18T19:00)"
        )

    def handle(self, *args, **options):
        city = options['city']
        level = options['level']
        randomness = options['randomness']
        departure_datetime = options.get('departure_datetime')
        return_datetime = options.get('return_datetime')

        if not (0 <= randomness <= 1):
            self.stdout.write(
                self.style.ERROR("L'argument --randomness doit être compris entre 0 et 1")
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Calcul du meilleur chemin pour city={city}, "
                f"niveau={level}, randomness={randomness}, "
                f"departure={departure_datetime}, return={return_datetime}"
            )
        )

        geojson = compute_best_route(
            randomness=randomness,
            city=city,
            departure_time=departure_datetime,
            return_time=return_datetime,
            level=level
        )
        save_geojson(geojson)
        print("Ca pasee")
        self.stdout.write(self.style.SUCCESS("✅ Itinéraire optimisé généré avec succès"))
