from datetime import timedelta
from io import BytesIO

from django.template.loader import render_to_string
from django.utils import timezone
from xhtml2pdf import pisa

from .models import RecurringSchedule


def generate_work_orders_for_range(date_from, date_to, created_by=None):
    created = []
    schedules = RecurringSchedule.objects.filter(is_active=True).select_related("contract", "company")
    for schedule in schedules:
        created.extend(schedule.generate_work_orders(date_from, date_to, created_by=created_by))
    return created


def generate_upcoming_work_orders(days=14, created_by=None):
    today = timezone.localdate()
    return generate_work_orders_for_range(today, today + timedelta(days=days), created_by=created_by)


def build_service_receipt_pdf(work_order):
    html = render_to_string("mobilewash/service_receipt_pdf.html", {"work_order": work_order})
    output = BytesIO()
    result = pisa.CreatePDF(html, dest=output)
    if result.err:
        raise RuntimeError("Impossible de generer le recu de service PDF.")
    output.seek(0)
    return output

