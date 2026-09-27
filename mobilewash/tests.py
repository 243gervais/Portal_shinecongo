from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from comptes.models import UserProfile
from .models import Contract, CorporateCompany, RecurringSchedule, Vehicle, WorkOrder, WorkOrderVehicle


def tiny_png(name="sig.png"):
    return SimpleUploadedFile(
        name,
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
        content_type="image/png",
    )


@override_settings(MEDIA_ROOT="/private/tmp/portal_shinecongo_mobilewash_test_media")
class MobileWashPhaseOneTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin", password="pass", is_superuser=True)
        self.manager = User.objects.create_user("manager", password="pass")
        self.field = User.objects.create_user("field", password="pass")
        self.other_field = User.objects.create_user("other", password="pass")
        self.manager.userprofile.role = UserProfile.MANAGER_ROLE
        self.manager.userprofile.save(update_fields=["role", "updated_at"])
        self.field.userprofile.role = UserProfile.EMPLOYEE_ROLE
        self.field.userprofile.save(update_fields=["role", "updated_at"])
        self.other_field.userprofile.role = UserProfile.EMPLOYEE_ROLE
        self.other_field.userprofile.save(update_fields=["role", "updated_at"])
        self.company = CorporateCompany.objects.create(legal_name="Acme SARL", telephone="+243")
        self.contract = Contract.objects.create(
            contract_number="CM-001",
            company=self.company,
            title="Package standard",
            start_date=date(2026, 1, 1),
            status="ACTIVE",
            monthly_package_price=Decimal("360.00"),
            included_washes_per_month=12,
            included_visits_per_month=4,
            service_location="Acme HQ",
            created_by=self.manager,
        )

    def create_work_order(self):
        scheduled_start = timezone.make_aware(timezone.datetime(2026, 1, 5, 8, 0))
        order = WorkOrder.objects.create(
            contract=self.contract,
            company=self.company,
            service_location="Acme HQ",
            scheduled_start=scheduled_start,
            planned_vehicles=2,
            team_leader=self.field,
        )
        order.assigned_employees.add(self.field)
        order.create_number()
        return order

    def test_duplicate_active_license_plate_is_rejected_per_company(self):
        Vehicle.objects.create(company=self.company, license_plate="abc123", is_active=True)
        duplicate = Vehicle(company=self.company, license_plate="ABC123", is_active=True)
        duplicate.clean()
        with self.assertRaises(Exception):
            duplicate.save()

    def test_contract_allowance_calculates_additional_washes(self):
        order = self.create_work_order()
        order.client_confirmed_at = timezone.now()
        order.status = WorkOrder.STATUS_COMPLETED
        order.save()
        for index in range(13):
            WorkOrderVehicle.objects.create(work_order=order, license_plate_snapshot=f"PLAQUE-{index}", status=WorkOrderVehicle.STATUS_COMPLETED)
        usage = self.contract.usage_for_period(date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(usage["used_washes"], 13)
        self.assertEqual(usage["billable_additional_washes"], 1)
        self.assertTrue(usage["allowance_exceeded"])

    def test_schedule_generation_is_idempotent(self):
        schedule = RecurringSchedule.objects.create(
            contract=self.contract,
            company=self.company,
            service_location="Acme HQ",
            weekday=0,
            planned_start_time=time(8, 0),
            planned_vehicles=12,
            start_date=date(2026, 1, 1),
        )
        schedule.default_assigned_team.add(self.field)
        first = schedule.generate_work_orders(date(2026, 1, 1), date(2026, 1, 31), created_by=self.manager)
        second = schedule.generate_work_orders(date(2026, 1, 1), date(2026, 1, 31), created_by=self.manager)
        self.assertEqual(len(first), 4)
        self.assertEqual(len(second), 0)
        self.assertEqual(WorkOrder.objects.count(), 4)

    def test_work_order_requires_confirmations_before_completion(self):
        order = self.create_work_order()
        WorkOrderVehicle.objects.create(work_order=order, license_plate_snapshot="A1", status=WorkOrderVehicle.STATUS_COMPLETED)
        with self.assertRaises(ValidationError):
            order.approve_completion(self.manager)

    def test_work_order_can_complete_after_review_and_signatures(self):
        order = self.create_work_order()
        WorkOrderVehicle.objects.create(work_order=order, license_plate_snapshot="A1", status=WorkOrderVehicle.STATUS_COMPLETED)
        order.associate_name = "Jean"
        order.client_representative_name = "Client"
        order.associate_signature = tiny_png("associate.png")
        order.client_signature = tiny_png("client.png")
        order.reviewed_by = self.manager
        order.reviewed_at = timezone.now()
        order.save()
        order.approve_completion(self.manager)
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.STATUS_COMPLETED)

    def test_field_associate_only_sees_assigned_work_orders(self):
        order = self.create_work_order()
        self.client.login(username="other", password="pass")
        response = self.client.get(reverse("mobilewash_work_order_detail", args=[order.id]))
        self.assertEqual(response.status_code, 403)
        self.client.login(username="field", password="pass")
        response = self.client.get(reverse("mobilewash_work_order_detail", args=[order.id]))
        self.assertEqual(response.status_code, 200)

    def test_manager_can_access_dashboard_and_field_cannot(self):
        self.client.login(username="manager", password="pass")
        self.assertEqual(self.client.get(reverse("mobilewash_dashboard")).status_code, 200)
        self.client.login(username="field", password="pass")
        self.assertEqual(self.client.get(reverse("mobilewash_dashboard")).status_code, 403)

    def test_cost_and_contribution_margin(self):
        order = self.create_work_order()
        WorkOrderVehicle.objects.create(work_order=order, license_plate_snapshot="A1", status=WorkOrderVehicle.STATUS_COMPLETED, billable_amount=Decimal("30.00"))
        order.machine_fuel_amount = Decimal("4.00")
        order.soap_cost = Decimal("2.00")
        order.transportation_cost = Decimal("10.00")
        order.save()
        self.assertEqual(order.direct_cost_amount, Decimal("16.00"))
        self.assertEqual(order.contribution_margin, Decimal("14.00"))

    def test_pdf_receipt_requires_authorized_user(self):
        order = self.create_work_order()
        self.client.login(username="field", password="pass")
        response = self.client.get(reverse("mobilewash_service_receipt_pdf", args=[order.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
