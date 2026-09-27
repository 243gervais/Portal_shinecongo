from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from mobilewash.services import generate_work_orders_for_range


class Command(BaseCommand):
    help = "Genere les ordres de travail mobiles depuis les plannings recurrents actifs."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="date_from", help="Date debut YYYY-MM-DD")
        parser.add_argument("--to", dest="date_to", help="Date fin YYYY-MM-DD")
        parser.add_argument("--days", type=int, default=14, help="Nombre de jours a generer si --to absent")

    def handle(self, *args, **options):
        try:
            date_from = timezone.datetime.strptime(options["date_from"], "%Y-%m-%d").date() if options["date_from"] else timezone.localdate()
            date_to = timezone.datetime.strptime(options["date_to"], "%Y-%m-%d").date() if options["date_to"] else date_from + timedelta(days=options["days"])
        except ValueError as exc:
            raise CommandError("Format de date invalide. Utilisez YYYY-MM-DD.") from exc
        created = generate_work_orders_for_range(date_from, date_to)
        self.stdout.write(self.style.SUCCESS(f"{len(created)} ordre(s) de travail mobile genere(s)."))

