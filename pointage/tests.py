from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from comptes.forms import get_water_purchase_default_amount
from lavages.models import CarWash
from pointage.models import ShiftDay
from sites.models import Location, SiteWaterPurchase


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    FINAL_REPORT_NOTIFICATION_EMAIL="mbadunkokorigervais@gmail.com",
)
class EmployeeDailyReportTests(TestCase):
    def setUp(self):
        self.site = Location.objects.create(
            nom="Ngaliema Test",
            adresse="Avenue Test",
            ville="Kinshasa",
            actif=True,
        )
        self.user = User.objects.create_user(
            username="jules",
            email="jules@example.com",
            password="TestPass123!",
        )
        self.user.userprofile.role = "EMPLOYE"
        self.user.userprofile.site = self.site
        self.user.userprofile.save()
        self.client.login(username="jules", password="TestPass123!")

    def test_employee_report_is_saved(self):
        today = timezone.localdate()
        CarWash.objects.create(
            employe=self.user,
            site=self.site,
            date=today,
            type_service="COMPLET",
            plaque="ABC123",
            montant=Decimal("13000.00"),
        )

        response = self.client.post(
            reverse("employe_daily_report"),
            data={
                "total_amount_reported_fc": "15000",
                "known_expense_transport_personnels_enabled": "1",
                "known_expense_transport_personnels_amount": "14000",
                "custom_expense_label": ["Achat eau"],
                "custom_expense_amount": ["2000"],
            },
        )

        self.assertEqual(response.status_code, 302)
        shift = ShiftDay.objects.get(employe=self.user, date=today)
        self.assertTrue(shift.daily_report_confirmed)
        self.assertEqual(shift.total_amount_reported_fc, Decimal("15000"))
        self.assertEqual(shift.daily_expenses_total_fc, Decimal("16000"))
        self.assertEqual(len(shift.daily_expense_items), 2)
        self.assertEqual(shift.daily_expense_items[0]["label"], "Transport de Personnels")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Rapport de fin de journée soumis", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["mbadunkokorigervais@gmail.com"])
        self.assertIn("Montant déclaré: 15 000 FC", mail.outbox[0].body)
        self.assertIn("Dépenses du jour: 16 000 FC", mail.outbox[0].body)

    def test_employee_dashboard_contains_instant_navigation(self):
        response = self.client.get(reverse("employe_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "window.instantNavigate")
        self.assertContains(response, "portal-instant-employee:")
        self.assertContains(response, "portal-activity-revision")
        self.assertContains(response, "revalidate")
        self.assertContains(response, reverse("employe_daily_report"))
        self.assertContains(response, "data-employee-route-card")
        self.assertContains(response, reverse("ajouter_lavage"))
        self.assertContains(response, reverse("employe_water_purchase"))
        self.assertContains(response, "Gestion de l'eau")
        self.assertContains(response, "Rapport du jour envoyé")
        self.assertContains(response, "Eau signalée aujourd'hui")
        self.assertNotContains(response, "Montant du jour")

    def test_employee_history_contains_mobile_friendly_instant_navigation_hooks(self):
        response = self.client.get(reverse("employe_historique"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "window.instantNavigate")
        self.assertContains(response, "portal-instant-employee:")
        self.assertContains(response, "touchstart")
        self.assertContains(response, reverse("mes_lavages"))
        self.assertContains(response, reverse("mes_problemes"))
        self.assertContains(response, "Rapports de fin de journée")
        self.assertContains(response, "Gestion de l'eau")
        self.assertContains(response, "Aucun montant n'est affiché dans cet espace")

    def test_employee_can_update_same_day_report(self):
        today = timezone.localdate()
        ShiftDay.objects.create(
            employe=self.user,
            site=self.site,
            date=today,
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("12000.00"),
            total_lavages_reported=1,
            daily_expenses=[
                {
                    "key": "transport_personnels",
                    "label": "Transport de Personnels",
                    "amount_fc": "12000.00",
                    "is_known": True,
                }
            ],
            daily_expenses_total_fc=Decimal("12000.00"),
        )

        response = self.client.post(
            reverse("employe_daily_report"),
            data={
                "total_amount_reported_fc": "17000",
                "known_expense_transport_personnels_enabled": "1",
                "known_expense_transport_personnels_amount": "10000",
                "custom_expense_label": ["Gasoil"],
                "custom_expense_amount": ["5000"],
            },
        )

        self.assertEqual(response.status_code, 302)
        shift = ShiftDay.objects.get(employe=self.user, date=today)
        self.assertTrue(shift.daily_report_confirmed)
        self.assertEqual(shift.total_amount_reported_fc, Decimal("17000"))
        self.assertEqual(shift.daily_expenses_total_fc, Decimal("15000"))
        self.assertEqual(len(shift.daily_expense_items), 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Rapport de fin de journée mis à jour", mail.outbox[0].subject)

    def test_unchecked_known_expenses_are_not_added_to_total(self):
        today = timezone.localdate()

        response = self.client.post(
            reverse("employe_daily_report"),
            data={
                "total_amount_reported_fc": "9000",
                "known_expense_transport_personnels_amount": "14000",
                "custom_expense_label": [""],
                "custom_expense_amount": [""],
            },
        )

        self.assertEqual(response.status_code, 302)
        shift = ShiftDay.objects.get(employe=self.user, date=today)
        self.assertEqual(shift.daily_expenses_total_fc, Decimal("0"))
        self.assertEqual(shift.daily_expense_items, [])

    def test_employee_can_signal_water_purchase_in_one_click(self):
        today = timezone.localdate()

        response = self.client.post(reverse("employe_water_purchase"))

        self.assertEqual(response.status_code, 302)
        purchase = SiteWaterPurchase.objects.get(site=self.site, purchase_date=today)
        self.assertEqual(purchase.billing_month, today.replace(day=1))
        self.assertEqual(purchase.amount_fc, get_water_purchase_default_amount(today))
        self.assertEqual(purchase.created_by, self.user)
        self.assertIn("Signalé via portail employé", purchase.notes)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Achat d'eau signalé", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["mbadunkokorigervais@gmail.com"])
        self.assertIn("Employé: jules", mail.outbox[0].body)
        self.assertIn("Site: Ngaliema Test", mail.outbox[0].body)
        self.assertIn("Montant enregistré: 22 000 FC", mail.outbox[0].body)

    def test_employee_water_purchase_page_renders(self):
        response = self.client.get(reverse("employe_water_purchase"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestion de l'eau du site")
        self.assertContains(response, "Confirmer que l'eau a été achetée aujourd'hui")
        self.assertContains(response, "Automatique")
        self.assertNotContains(response, "Tarif appliqué")

    def test_employee_water_purchase_prevents_same_day_duplicate(self):
        today = timezone.localdate()
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=today.replace(day=1),
            purchase_date=today,
            amount_fc=get_water_purchase_default_amount(today),
            notes="Signalé via portail employé par jules.",
            created_by=self.user,
        )

        response = self.client.post(reverse("employe_water_purchase"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SiteWaterPurchase.objects.filter(site=self.site, purchase_date=today).count(), 1)
        self.assertContains(response, "déjà été signalé")

    def test_employee_history_lists_water_and_report_entries_without_amounts(self):
        today = timezone.localdate()
        ShiftDay.objects.create(
            employe=self.user,
            site=self.site,
            date=today,
            clock_in_time=timezone.now(),
            clock_out_time=timezone.now(),
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("18000.00"),
            total_lavages_reported=2,
            daily_expenses=[
                {
                    "key": "transport_personnels",
                    "label": "Transport de Personnels",
                    "amount_fc": "14000.00",
                    "is_known": True,
                }
            ],
            daily_expenses_total_fc=Decimal("14000.00"),
        )
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=today.replace(day=1),
            purchase_date=today,
            amount_fc=get_water_purchase_default_amount(today),
            notes="Signalé via portail employé par jules.",
            created_by=self.user,
        )

        response = self.client.get(reverse("employe_historique"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rapport enregistré")
        self.assertContains(response, "Achat du")
        self.assertContains(response, "Transmis")
        self.assertContains(response, "2 lavages")
        self.assertNotContains(response, "18 000 FC")
        self.assertNotContains(response, "14 000 FC")
        self.assertNotContains(response, "22 000 FC")

    def test_employee_water_page_reflects_admin_edit_and_delete(self):
        today = timezone.localdate()
        purchase = SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=today.replace(day=1),
            purchase_date=today,
            amount_fc=get_water_purchase_default_amount(today),
            notes="Signalé via portail employé par jules.",
            created_by=self.user,
        )

        response = self.client.get(reverse("employe_water_purchase"))
        self.assertContains(response, "Déjà signalé aujourd'hui")
        self.assertContains(response, today.strftime("%d/%m/%Y"))
        self.assertNotContains(response, "22000 FC")

        admin_user = User.objects.create_superuser(
            username="admin_water_sync",
            email="admin_water_sync@example.com",
            password="AdminPass123!",
        )
        admin_client = self.client_class()
        admin_client.login(username="admin_water_sync", password="AdminPass123!")

        edit_response = admin_client.post(
            reverse("admin_edit_water_purchase", kwargs={"purchase_id": purchase.id}),
            data={
                "site": str(self.site.id),
                "billing_month": today.strftime("%Y-%m"),
                "purchase_date": today.strftime("%Y-%m-%d"),
                "amount_fc": "25000",
                "notes": "Montant corrigé par admin",
            },
        )
        self.assertEqual(edit_response.status_code, 302)

        response = self.client.get(reverse("employe_water_purchase"))
        self.assertContains(response, "Transmis à l'admin")
        self.assertNotContains(response, "25000 FC")

        delete_response = admin_client.post(
            reverse("admin_delete_water_purchase", kwargs={"purchase_id": purchase.id})
        )
        self.assertEqual(delete_response.status_code, 302)

        response = self.client.get(reverse("employe_water_purchase"))
        self.assertNotContains(response, "Achat enregistré pour")
        self.assertContains(response, "Confirmer que l'eau a été achetée aujourd'hui")


class AdminDashboardDailyReportMessagesTests(TestCase):
    def setUp(self):
        self.site = Location.objects.create(
            nom="Ngaliema Test",
            adresse="Avenue Test",
            ville="Kinshasa",
            actif=True,
        )
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="AdminPass123!",
        )
        self.employee = User.objects.create_user(
            username="mike",
            email="mike@example.com",
            password="TestPass123!",
        )
        self.employee.userprofile.role = "EMPLOYE"
        self.employee.userprofile.site = self.site
        self.employee.userprofile.save()
        self.client.login(username="admin", password="AdminPass123!")

    def test_admin_dashboard_shows_daily_report_message(self):
        today = timezone.localdate()
        ShiftDay.objects.create(
            employe=self.employee,
            site=self.site,
            date=today,
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("25000.00"),
            total_lavages_reported=3,
            daily_expenses=[
                {
                    "key": "transport_personnels",
                    "label": "Transport de Personnels",
                    "amount_fc": "14000.00",
                    "is_known": True,
                }
            ],
            daily_expenses_total_fc=Decimal("14000.00"),
        )

        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Boite Admin")
        self.assertContains(response, "Messages - Rapports de fin de journée")
        self.assertContains(response, "mike")
        self.assertContains(response, "25 000")
        self.assertContains(response, "14 000")
        self.assertContains(response, "Transport de Personnels")
        self.admin_user.userprofile.refresh_from_db()
        self.assertIsNotNone(self.admin_user.userprofile.admin_reports_last_seen_at)

    def test_admin_dashboard_shows_modify_and_delete_actions_for_daily_report(self):
        today = timezone.localdate()
        shift = ShiftDay.objects.create(
            employe=self.employee,
            site=self.site,
            date=today,
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("25000.00"),
            total_lavages_reported=3,
            daily_expenses_total_fc=Decimal("14000.00"),
        )

        response = self.client.get(reverse("admin_dashboard"))

        self.assertContains(response, reverse("admin_edit_pointage", args=[self.site.id, shift.id]))
        self.assertContains(response, reverse("admin_delete_daily_report", args=[self.site.id, shift.id]))

    def test_admin_can_delete_only_daily_report_and_keep_pointage(self):
        today = timezone.localdate()
        shift = ShiftDay.objects.create(
            employe=self.employee,
            site=self.site,
            date=today,
            clock_in_time=timezone.now(),
            clock_out_time=timezone.now(),
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("25000.00"),
            total_lavages_reported=3,
            daily_expenses=[
                {
                    "key": "transport_personnels",
                    "label": "Transport de Personnels",
                    "amount_fc": "14000.00",
                    "is_known": True,
                }
            ],
            daily_expenses_total_fc=Decimal("14000.00"),
        )

        response = self.client.post(
            reverse("admin_delete_daily_report", args=[self.site.id, shift.id]),
            data={"motif": "Rapport envoyé par erreur"},
        )

        self.assertEqual(response.status_code, 302)
        shift.refresh_from_db()
        self.assertFalse(shift.daily_report_confirmed)
        self.assertEqual(shift.total_amount_reported_fc, Decimal("0"))
        self.assertEqual(shift.total_lavages_reported, 0)
        self.assertEqual(shift.daily_expenses_total_fc, Decimal("0"))
        self.assertEqual(shift.daily_expenses, [])
        self.assertIsNotNone(shift.clock_in_time)
        self.assertIsNotNone(shift.clock_out_time)

    def test_employee_history_shows_pending_after_admin_deletes_daily_report(self):
        today = timezone.localdate()
        shift = ShiftDay.objects.create(
            employe=self.employee,
            site=self.site,
            date=today,
            clock_in_time=timezone.now(),
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("18000.00"),
            total_lavages_reported=2,
        )

        self.client.post(
            reverse("admin_delete_daily_report", args=[self.site.id, shift.id]),
            data={"motif": "Rapport à reprendre"},
        )

        self.client.logout()
        self.client.login(username="mike", password="TestPass123!")
        response = self.client.get(reverse("employe_historique"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "En attente")
        self.assertNotContains(response, "Enregistré")
