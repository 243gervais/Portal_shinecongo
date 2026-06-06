from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.db.models import Sum
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from comptes.forms import get_water_purchase_default_amount
from lavages.models import CarWash
from pointage.models import ShiftDay
from pointage.report_sync import ADMIN_CORRECTION_SOURCE, sync_site_finance_from_daily_reports
from sites.models import DailyBankDeposit, Location, SiteLossEntry, SiteWaterPurchase


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
        self.admin_user = User.objects.create_superuser(
            username="report_admin",
            email="report_admin@example.com",
            password="AdminPass123!",
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
        self.assertEqual(len(mail.outbox[0].alternatives), 1)
        html_content, mimetype = mail.outbox[0].alternatives[0]
        self.assertEqual(mimetype, "text/html")
        self.assertIn("Rapport de fin de journée", html_content)
        self.assertIn("Transport de Personnels", html_content)
        self.assertIn("Achat eau", html_content)

    def test_final_report_auto_syncs_daily_total_expenses_and_bank_deposit(self):
        today = timezone.localdate()
        CarWash.objects.create(
            employe=self.user,
            site=self.site,
            date=today,
            type_service="COMPLET",
            plaque="ABC123",
            montant=Decimal("28000.00"),
        )

        response = self.client.post(
            reverse("employe_daily_report"),
            data={
                "total_amount_reported_fc": "60000",
                "known_expense_transport_personnels_enabled": "1",
                "known_expense_transport_personnels_amount": "24000",
                "custom_expense_label": [""],
                "custom_expense_amount": [""],
            },
        )

        self.assertEqual(response.status_code, 302)
        auto_adjustment = CarWash.objects.get(
            site=self.site,
            date=today,
            is_system_generated=True,
            system_source="DAILY_REPORT_SYNC",
        )
        self.assertEqual(auto_adjustment.montant, Decimal("32000.00"))
        self.assertEqual(auto_adjustment.employe, self.admin_user)
        self.assertIn("Ajustement automatique du rapport de fin de journée", auto_adjustment.notes)

        auto_expense = SiteLossEntry.objects.get(
            site=self.site,
            date=today,
            is_system_generated=True,
            system_source="DAILY_REPORT_SYNC",
            title="Transport de Personnels",
        )
        self.assertEqual(auto_expense.amount, Decimal("24000.00"))
        self.assertEqual(auto_expense.funding_source, "CAISSE")

        auto_deposit = DailyBankDeposit.objects.get(site=self.site, date=today)
        self.assertTrue(auto_deposit.is_system_generated)
        self.assertEqual(auto_deposit.amount, Decimal("36000.00"))
        self.assertIn("rapport de fin de journée", auto_deposit.notes.lower())

    def test_updating_final_report_recomputes_auto_finance_records(self):
        today = timezone.localdate()
        CarWash.objects.create(
            employe=self.user,
            site=self.site,
            date=today,
            type_service="COMPLET",
            plaque="ABC123",
            montant=Decimal("28000.00"),
        )

        self.client.post(
            reverse("employe_daily_report"),
            data={
                "total_amount_reported_fc": "60000",
                "known_expense_transport_personnels_enabled": "1",
                "known_expense_transport_personnels_amount": "24000",
                "custom_expense_label": [""],
                "custom_expense_amount": [""],
            },
        )

        response = self.client.post(
            reverse("employe_daily_report"),
            data={
                "total_amount_reported_fc": "70000",
                "known_expense_transport_personnels_enabled": "1",
                "known_expense_transport_personnels_amount": "10000",
                "custom_expense_label": ["Savon"],
                "custom_expense_amount": ["5000"],
            },
        )

        self.assertEqual(response.status_code, 302)
        auto_adjustment = CarWash.objects.get(
            site=self.site,
            date=today,
            is_system_generated=True,
            system_source="DAILY_REPORT_SYNC",
        )
        self.assertEqual(auto_adjustment.montant, Decimal("42000.00"))

        auto_expenses = SiteLossEntry.objects.filter(
            site=self.site,
            date=today,
            is_system_generated=True,
            system_source="DAILY_REPORT_SYNC",
        ).order_by("title")
        self.assertEqual(auto_expenses.count(), 2)
        self.assertEqual(auto_expenses[0].title, "Savon")
        self.assertEqual(auto_expenses[0].amount, Decimal("5000.00"))
        self.assertEqual(auto_expenses[1].title, "Transport de Personnels")
        self.assertEqual(auto_expenses[1].amount, Decimal("10000.00"))

        auto_deposit = DailyBankDeposit.objects.get(site=self.site, date=today)
        self.assertEqual(auto_deposit.amount, Decimal("55000.00"))

    def test_admin_delete_daily_report_clears_auto_synced_finance_records(self):
        today = timezone.localdate()
        CarWash.objects.create(
            employe=self.user,
            site=self.site,
            date=today,
            type_service="COMPLET",
            plaque="ABC123",
            montant=Decimal("28000.00"),
        )
        self.client.post(
            reverse("employe_daily_report"),
            data={
                "total_amount_reported_fc": "60000",
                "known_expense_transport_personnels_enabled": "1",
                "known_expense_transport_personnels_amount": "24000",
                "custom_expense_label": [""],
                "custom_expense_amount": [""],
            },
        )

        shift = ShiftDay.objects.get(employe=self.user, date=today)
        admin_client = self.client_class()
        admin_client.login(username="report_admin", password="AdminPass123!")
        response = admin_client.post(
            reverse("admin_delete_daily_report", args=[self.site.id, shift.id]),
            data={"motif": "Annulation du rapport automatique"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            CarWash.objects.filter(
                site=self.site,
                date=today,
                is_system_generated=True,
                system_source="DAILY_REPORT_SYNC",
            ).exists()
        )
        self.assertFalse(
            SiteLossEntry.objects.filter(
                site=self.site,
                date=today,
                is_system_generated=True,
                system_source="DAILY_REPORT_SYNC",
            ).exists()
        )
        self.assertFalse(
            DailyBankDeposit.objects.filter(
                site=self.site,
                date=today,
                is_system_generated=True,
                system_source="DAILY_REPORT_SYNC",
            ).exists()
        )
        self.assertEqual(
            CarWash.objects.filter(site=self.site, date=today, is_system_generated=False).count(),
            1,
        )

    def test_admin_added_wash_keeps_cash_correction_additive_after_report(self):
        today = timezone.localdate()
        CarWash.objects.create(
            employe=self.user,
            site=self.site,
            date=today,
            type_service="COMPLET",
            plaque="ABC123",
            montant=Decimal("28000.00"),
        )
        self.client.post(
            reverse("employe_daily_report"),
            data={
                "total_amount_reported_fc": "60000",
                "known_expense_transport_personnels_enabled": "1",
                "known_expense_transport_personnels_amount": "24000",
                "custom_expense_label": [""],
                "custom_expense_amount": [""],
            },
        )

        employee_two = User.objects.create_user(
            username="mike",
            email="mike@example.com",
            password="TestPass123!",
        )
        employee_two.userprofile.role = "EMPLOYE"
        employee_two.userprofile.site = self.site
        employee_two.userprofile.save()

        admin_client = self.client_class()
        admin_client.login(username="report_admin", password="AdminPass123!")
        response = admin_client.post(
            reverse("admin_add_wash", args=[self.site.id]),
            data={
                "employe": str(employee_two.id),
                "date": today.strftime("%Y-%m-%d"),
                "type_service": "COMPLET",
                "plaque": "XYZ987",
                "montant": "10000",
                "notes": "Lavage oublié puis ajouté par admin",
            },
        )

        self.assertEqual(response.status_code, 302)
        auto_adjustment = CarWash.objects.get(
            site=self.site,
            date=today,
            is_system_generated=True,
            system_source="DAILY_REPORT_SYNC",
        )
        correction_wash = CarWash.objects.get(
            site=self.site,
            date=today,
            plaque="XYZ987",
            is_system_generated=False,
        )
        self.assertEqual(correction_wash.system_source, ADMIN_CORRECTION_SOURCE)

        sync_site_finance_from_daily_reports(self.site, today, actor=self.admin_user)
        auto_adjustment.refresh_from_db()
        self.assertEqual(auto_adjustment.montant, Decimal("32000.00"))
        total_cash_flow = CarWash.objects.filter(site=self.site, date=today).aggregate(
            total=Sum("montant")
        )["total"]
        self.assertEqual(total_cash_flow, Decimal("70000.00"))

        auto_deposit = DailyBankDeposit.objects.get(site=self.site, date=today)
        self.assertEqual(auto_deposit.amount, Decimal("36000.00"))

    def test_admin_added_wash_redirects_back_to_same_date_and_updates_week_total(self):
        target_date = timezone.localdate() - timedelta(days=7)
        admin_client = self.client_class()
        admin_client.login(username="report_admin", password="AdminPass123!")

        response = admin_client.post(
            reverse("admin_add_wash", args=[self.site.id]),
            data={
                "employe": str(self.user.id),
                "date": target_date.strftime("%Y-%m-%d"),
                "type_service": "COMPLET",
                "plaque": "WEEK123",
                "montant": "15000",
                "notes": "Ajout admin semaine précédente",
            },
        )

        expected_redirect = (
            f"{reverse('admin_site_detail', args=[self.site.id])}"
            f"?date_debut={target_date.strftime('%Y-%m-%d')}&date_fin={target_date.strftime('%Y-%m-%d')}"
        )
        self.assertRedirects(response, expected_redirect, fetch_redirect_response=False)

        detail_response = admin_client.get(expected_redirect)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.context["selected_single_date"], target_date)
        self.assertEqual(detail_response.context["chiffre_week"], Decimal("15000"))
        self.assertContains(detail_response, "15 000 FC")

    def test_employee_dashboard_contains_instant_navigation(self):
        response = self.client.get(reverse("employe_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "portal-root")
        self.assertContains(response, "portal-bootstrap")
        self.assertContains(response, "portal-app.js")
        self.assertContains(response, '"mode": "employee"')

        api_response = self.client.get(reverse("portal_api_employee_dashboard"))
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()
        self.assertEqual(payload["site"]["nom"], "Ngaliema Test")
        self.assertIn("lavages_today", payload["stats"])
        self.assertNotIn("montant_du_jour", payload["stats"])

    def test_employee_history_contains_mobile_friendly_instant_navigation_hooks(self):
        response = self.client.get(reverse("employe_historique"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "portal-root")
        self.assertContains(response, "portal-app.js")
        self.assertContains(response, '"mode": "employee"')

        summary_response = self.client.get(reverse("portal_api_employee_history_summary"))
        self.assertEqual(summary_response.status_code, 200)
        summary = summary_response.json()
        self.assertEqual(summary["site"]["nom"], "Ngaliema Test")
        self.assertIn("lavages", summary["counts"])
        self.assertIn("problemes", summary["counts"])

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
        self.assertEqual(len(mail.outbox[0].alternatives), 1)
        self.assertIn("Gasoil", mail.outbox[0].alternatives[0][0])

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
        self.assertEqual(purchase.supplier.name, "Honosha's Forage")
        self.assertEqual(purchase.created_by, self.user)
        self.assertIn("Signalé via portail employé", purchase.notes)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Achat d'eau signalé", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["mbadunkokorigervais@gmail.com"])
        self.assertIn("Employé: jules", mail.outbox[0].body)
        self.assertIn("Site: Ngaliema Test", mail.outbox[0].body)
        self.assertIn("Fournisseur: Honosha's Forage", mail.outbox[0].body)
        self.assertIn("Montant enregistré: 22 000 FC", mail.outbox[0].body)
        self.assertEqual(len(mail.outbox[0].alternatives), 1)
        html_content, mimetype = mail.outbox[0].alternatives[0]
        self.assertEqual(mimetype, "text/html")
        self.assertIn("Achat d'eau signalé", html_content)
        self.assertIn("Honosha", html_content)
        self.assertIn("22 000 FC", html_content)

    def test_employee_water_purchase_page_renders(self):
        response = self.client.get(reverse("employe_water_purchase"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "portal-root")
        self.assertContains(response, "portal-app.js")

        api_response = self.client.get(reverse("portal_api_employee_water"))
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()
        self.assertEqual(payload["default_supplier_name"], "Honosha's Forage")
        self.assertNotIn("default_amount", payload)

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

        response = self.client.post(reverse("portal_api_employee_water"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(SiteWaterPurchase.objects.filter(site=self.site, purchase_date=today).count(), 1)
        self.assertIn("déjà été signalé", response.json()["message"])

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

        reports_response = self.client.get(reverse("portal_api_employee_history_reports"))
        water_response = self.client.get(reverse("portal_api_employee_history_water"))

        self.assertEqual(reports_response.status_code, 200)
        self.assertEqual(water_response.status_code, 200)

        reports_payload = reports_response.json()
        water_payload = water_response.json()
        self.assertEqual(reports_payload["results"][0]["report_status_label"], "Envoyé")
        self.assertEqual(reports_payload["results"][0]["total_lavages_reported"], 2)
        self.assertNotIn("total_amount_reported_fc", reports_payload["results"][0])
        self.assertNotIn("daily_expenses_total_fc", reports_payload["results"][0])
        self.assertEqual(water_payload["results"][0]["supplier_name"], "Honosha's Forage")
        self.assertNotIn("amount_fc", water_payload["results"][0])

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

        response = self.client.get(reverse("portal_api_employee_water"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNotNone(payload["today_purchase"])
        self.assertEqual(payload["today_purchase"]["purchase_date"], today.strftime("%Y-%m-%d"))

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

        response = self.client.get(reverse("portal_api_employee_water"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["today_purchase"]["notes"], "Montant corrigé par admin")
        self.assertNotIn("amount_fc", payload["today_purchase"])

        delete_response = admin_client.post(
            reverse("admin_delete_water_purchase", kwargs={"purchase_id": purchase.id})
        )
        self.assertEqual(delete_response.status_code, 302)

        response = self.client.get(reverse("portal_api_employee_water"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["today_purchase"])


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
        response = self.client.get(reverse("portal_api_employee_history_reports"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["results"][0]["report_status_label"], "En attente")
