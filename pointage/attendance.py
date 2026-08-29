from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone


SHIFT_START_TIME = time(hour=9, minute=0)
SHIFT_END_TIME = time(hour=19, minute=30)
SHIFT_GRACE_MINUTES = 30
WORKDAY_WEEKDAYS = {0, 1, 2, 3, 4, 5}
PENALTY_START_DATE = date(2026, 9, 1)
LATE_PENALTY_USD = Decimal("3")
ABSENT_PENALTY_USD = Decimal("5")


def is_workday(target_date):
    return target_date.weekday() in WORKDAY_WEEKDAYS


def shift_start_datetime(target_date):
    return timezone.make_aware(datetime.combine(target_date, SHIFT_START_TIME))


def shift_grace_deadline_datetime(target_date):
    return shift_start_datetime(target_date) + timedelta(minutes=SHIFT_GRACE_MINUTES)


def shift_end_datetime(target_date):
    return timezone.make_aware(datetime.combine(target_date, SHIFT_END_TIME))


def attendance_schedule_context():
    grace_label = (
        datetime.combine(timezone.localdate(), SHIFT_START_TIME)
        + timedelta(minutes=SHIFT_GRACE_MINUTES)
    ).strftime("%H:%M")
    return {
        "start_label": SHIFT_START_TIME.strftime("%H:%M"),
        "grace_label": grace_label,
        "end_label": SHIFT_END_TIME.strftime("%H:%M"),
        "workdays_label": "Lundi à samedi",
        "penalty_start_date": PENALTY_START_DATE.isoformat(),
    }


def _reference_localtime(reference_time=None):
    if reference_time is None:
        reference_time = timezone.now()
    return timezone.localtime(reference_time)


def get_clock_in_status(target_date, clock_in_time=None, *, reference_time=None):
    if clock_in_time:
        local_clock_in = timezone.localtime(clock_in_time)
        deadline = timezone.localtime(shift_grace_deadline_datetime(target_date))
        if local_clock_in <= deadline:
            return {
                "code": "PRESENT",
                "label": "Présent",
                "detail": f"Photo de début validée à {local_clock_in:%H:%M}.",
            }
        return {
            "code": "LATE",
            "label": "Retard",
            "detail": f"Arrivée validée à {local_clock_in:%H:%M} après {deadline:%H:%M}.",
        }

    if not is_workday(target_date):
        return {
            "code": "OFF",
            "label": "Repos",
            "detail": "Aucune présence requise le dimanche.",
        }

    reference_local = _reference_localtime(reference_time)
    deadline = timezone.localtime(shift_grace_deadline_datetime(target_date))
    if target_date < reference_local.date():
        return {
            "code": "ABSENT",
            "label": "Absent",
            "detail": "Aucune photo de début de journée reçue.",
        }
    if target_date == reference_local.date() and reference_local >= deadline:
        return {
            "code": "ABSENT",
            "label": "Absent",
            "detail": f"Aucune arrivée reçue avant {deadline:%H:%M}.",
        }
    return {
        "code": "PENDING",
        "label": "En attente",
        "detail": "L'arrivée de début de journée n'a pas encore été envoyée.",
    }


def get_clock_out_status(target_date, clock_out_time=None, *, reference_time=None):
    if clock_out_time:
        local_clock_out = timezone.localtime(clock_out_time)
        return {
            "code": "COMPLETE",
            "label": "Clôturée",
            "detail": f"Photo de fin validée à {local_clock_out:%H:%M}.",
        }

    if not is_workday(target_date):
        return {
            "code": "OFF",
            "label": "Repos",
            "detail": "Aucune fin de journée requise le dimanche.",
        }

    reference_local = _reference_localtime(reference_time)
    if target_date < reference_local.date():
        return {
            "code": "MISSING",
            "label": "Sortie manquante",
            "detail": "Aucune photo de fin de journée reçue.",
        }

    return {
        "code": "OPEN",
        "label": "En service",
        "detail": "La fin de journée n'a pas encore été envoyée.",
    }


def attendance_penalty_usd(target_date, attendance_status_code):
    if target_date < PENALTY_START_DATE or not is_workday(target_date):
        return Decimal("0")
    if attendance_status_code == "LATE":
        return LATE_PENALTY_USD
    if attendance_status_code == "ABSENT":
        return ABSENT_PENALTY_USD
    return Decimal("0")


def attendance_penalty_label(amount):
    amount = Decimal(amount or 0)
    if amount <= 0:
        return ""
    return f"${amount:,.0f}".replace(",", " ")
