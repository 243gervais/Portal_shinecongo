import logging

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from sites.models import SiteJournalEntry


logger = logging.getLogger(__name__)


def _smtp_delivery_ready():
    email_backend = getattr(settings, "EMAIL_BACKEND", "")
    uses_smtp_backend = email_backend.endswith("smtp.EmailBackend")
    if not uses_smtp_backend:
        return True

    return all(
        [
            getattr(settings, "EMAIL_HOST", ""),
            getattr(settings, "EMAIL_HOST_USER", ""),
            getattr(settings, "EMAIL_HOST_PASSWORD", ""),
        ]
    )


class Command(BaseCommand):
    help = "Envoie les rappels email programmés depuis le journal du site."

    def add_arguments(self, parser):
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="N'affiche pas le résumé quand aucun rappel n'est traité.",
        )

    def handle(self, *args, **options):
        quiet = options["quiet"]
        now = timezone.now()

        if not _smtp_delivery_ready():
            message = "Configuration email SMTP incomplète: rappels du journal non envoyés."
            logger.warning(message)
            if not quiet:
                self.stdout.write(self.style.WARNING(message))
            return

        due_entries = (
            SiteJournalEntry.objects.filter(
                reminder_at__isnull=False,
                reminder_sent_at__isnull=True,
                reminder_at__lte=now,
            )
            .select_related("site", "created_by")
            .order_by("reminder_at", "created_at")
        )

        sent_count = 0
        for entry in due_entries:
            recipient = (entry.reminder_email or "").strip()
            if not recipient:
                logger.warning("Aucun email de rappel défini pour l'entrée de journal %s", entry.pk)
                continue

            reminder_time = timezone.localtime(entry.reminder_at)
            amount_line = (
                f"Montant lié: {entry.amount_fc:,.0f} FC".replace(",", " ")
                if entry.amount_fc is not None
                else "Montant lié: non renseigné"
            )
            created_by = entry.created_by.get_full_name() or entry.created_by.username if entry.created_by else "Administrateur"

            subject = f"Rappel journal du site - {entry.site.nom} - {entry.title}"
            message = "\n".join(
                [
                    f"Site: {entry.site.nom}",
                    f"Catégorie: {entry.get_category_display()}",
                    f"Date du journal: {entry.entry_date.strftime('%d/%m/%Y')}",
                    f"Rappel prévu: {reminder_time.strftime('%d/%m/%Y %H:%M')} (heure de Kinshasa)",
                    f"Enregistré par: {created_by}",
                    amount_line,
                    "",
                    f"Titre: {entry.title}",
                    f"Détails: {entry.description or 'Aucun détail supplémentaire.'}",
                ]
            )

            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    recipient_list=[recipient],
                    fail_silently=False,
                )
            except Exception:
                logger.exception("Impossible d'envoyer le rappel du journal du site %s", entry.pk)
                continue

            entry.reminder_sent_at = timezone.now()
            entry.save(update_fields=["reminder_sent_at"])
            sent_count += 1

        if not quiet or sent_count:
            self.stdout.write(self.style.SUCCESS(f"{sent_count} rappel(s) du journal envoyé(s)."))
