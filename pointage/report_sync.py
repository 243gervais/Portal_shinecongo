from collections import OrderedDict
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum

from lavages.models import CarWash
from pointage.models import ShiftDay
from sites.models import DailyBankDeposit, SiteLossEntry

DAILY_REPORT_SYNC_SOURCE = "DAILY_REPORT_SYNC"
ADMIN_CORRECTION_SOURCE = "ADMIN_CORRECTION"
AUTO_REPORT_ADJUSTMENT_NOTE = "Ajustement automatique du rapport de fin de journée."
AUTO_REPORT_DEPOSIT_NOTE = "Dépôt bancaire synchronisé automatiquement depuis le rapport de fin de journée."
AUTO_REPORT_EXPENSE_DESCRIPTION = "Dépense synchronisée automatiquement depuis le rapport de fin de journée."

KNOWN_EXPENSE_CATEGORY_MAP = {
    "transport_personnels": "TRANSPORT",
}


def _to_decimal(value):
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


def _is_admin_actor(user):
    if not user:
        return False
    if getattr(user, "is_superuser", False):
        return True
    profile = getattr(user, "userprofile", None)
    return bool(profile and getattr(profile, "role", "") == "ADMIN")


def _get_sync_owner_user(site, actor=None):
    if _is_admin_actor(actor):
        return actor

    existing_auto_owner = CarWash.objects.filter(
        site=site,
        is_system_generated=True,
        system_source=DAILY_REPORT_SYNC_SOURCE,
    ).select_related("employe").order_by("id").first()
    if existing_auto_owner and existing_auto_owner.employe_id:
        return existing_auto_owner.employe

    admin_user = User.objects.filter(is_superuser=True).order_by("id").first()
    if admin_user:
        return admin_user

    admin_profile_user = User.objects.filter(
        userprofile__role="ADMIN",
        userprofile__actif=True,
    ).order_by("id").first()
    if admin_profile_user:
        return admin_profile_user

    if actor:
        return actor

    return User.objects.filter(userprofile__site=site).order_by("id").first()


def _normalize_expense_identifier(item):
    key = str(item.get("key", "")).strip()
    label = str(item.get("label", "")).strip()
    if key:
        return f"known::{key}", key, label
    normalized_label = " ".join(label.lower().split())
    return f"custom::{normalized_label}", "", label


def _build_expense_summary_rows(confirmed_shifts):
    aggregated = OrderedDict()

    for shift in confirmed_shifts:
        employee_name = shift.employe.get_full_name() or shift.employe.username
        for item in shift.daily_expense_items:
            identifier, expense_key, label = _normalize_expense_identifier(item)
            if not label:
                continue

            bucket = aggregated.setdefault(
                identifier,
                {
                    "key": expense_key,
                    "label": label,
                    "amount": Decimal("0"),
                    "employee_names": [],
                },
            )
            bucket["amount"] += _to_decimal(item.get("amount_fc"))
            if employee_name not in bucket["employee_names"]:
                bucket["employee_names"].append(employee_name)

    return list(aggregated.values())


@transaction.atomic
def sync_site_finance_from_daily_reports(site, target_date, actor=None):
    confirmed_shifts = list(
        ShiftDay.objects.filter(
            site=site,
            date=target_date,
            daily_report_confirmed=True,
        ).select_related("employe").order_by("id")
    )

    sync_owner = _get_sync_owner_user(site, actor=actor)

    auto_adjustments_qs = CarWash.objects.filter(
        site=site,
        date=target_date,
        is_system_generated=True,
        system_source=DAILY_REPORT_SYNC_SOURCE,
    ).order_by("id")
    auto_losses_qs = SiteLossEntry.objects.filter(
        site=site,
        date=target_date,
        is_system_generated=True,
        system_source=DAILY_REPORT_SYNC_SOURCE,
    ).order_by("id")
    auto_deposit = DailyBankDeposit.objects.filter(site=site, date=target_date).first()

    if not confirmed_shifts:
        auto_adjustments_qs.delete()
        auto_losses_qs.delete()
        if auto_deposit and auto_deposit.is_system_generated and auto_deposit.system_source == DAILY_REPORT_SYNC_SOURCE:
            auto_deposit.delete()
        return {
            "reported_total": Decimal("0"),
            "base_cash_flow": Decimal("0"),
            "adjustment_amount": Decimal("0"),
            "daily_expenses_total": Decimal("0"),
            "bank_deposit_amount": Decimal("0"),
            "report_count": 0,
        }

    reported_total = _to_decimal(
        ShiftDay.objects.filter(
            site=site,
            date=target_date,
            daily_report_confirmed=True,
        ).aggregate(total=Sum("total_amount_reported_fc"))["total"]
    )

    base_cash_flow = _to_decimal(
        CarWash.objects.filter(site=site, date=target_date)
        .exclude(is_system_generated=True, system_source=DAILY_REPORT_SYNC_SOURCE)
        .exclude(system_source=ADMIN_CORRECTION_SOURCE)
        .aggregate(total=Sum("montant"))["total"]
    )

    adjustment_amount = reported_total - base_cash_flow
    if adjustment_amount < 0:
        adjustment_amount = Decimal("0")

    expense_rows = _build_expense_summary_rows(confirmed_shifts)
    daily_expenses_total = sum((row["amount"] for row in expense_rows), Decimal("0"))
    bank_deposit_amount = reported_total - daily_expenses_total
    if bank_deposit_amount < 0:
        bank_deposit_amount = Decimal("0")

    auto_adjustments = list(auto_adjustments_qs)
    if adjustment_amount > 0 and sync_owner:
        adjustment_notes = (
            f"{AUTO_REPORT_ADJUSTMENT_NOTE} "
            f"Total déclaré: {reported_total:,.0f} FC. "
            f"Montants déjà saisis: {base_cash_flow:,.0f} FC."
        ).replace(",", " ")
        primary_adjustment = auto_adjustments[0] if auto_adjustments else None
        if primary_adjustment:
            primary_adjustment.employe = sync_owner
            primary_adjustment.type_service = "COMPLET"
            primary_adjustment.plaque = ""
            primary_adjustment.montant = adjustment_amount
            primary_adjustment.notes = adjustment_notes
            primary_adjustment.is_system_generated = True
            primary_adjustment.system_source = DAILY_REPORT_SYNC_SOURCE
            primary_adjustment.save(
                update_fields=[
                    "employe",
                    "type_service",
                    "plaque",
                    "montant",
                    "notes",
                    "is_system_generated",
                    "system_source",
                    "updated_at",
                ]
            )
        else:
            primary_adjustment = CarWash.objects.create(
                employe=sync_owner,
                site=site,
                date=target_date,
                type_service="COMPLET",
                plaque="",
                montant=adjustment_amount,
                notes=adjustment_notes,
                is_system_generated=True,
                system_source=DAILY_REPORT_SYNC_SOURCE,
            )
        if len(auto_adjustments) > 1:
            CarWash.objects.filter(id__in=[item.id for item in auto_adjustments[1:]]).delete()
    else:
        auto_adjustments_qs.delete()

    existing_loss_map = {entry.title: entry for entry in auto_losses_qs}
    desired_titles = set()
    for row in expense_rows:
        title = row["label"]
        desired_titles.add(title)
        entry = existing_loss_map.get(title)
        description = AUTO_REPORT_EXPENSE_DESCRIPTION
        if row["employee_names"]:
            description = (
                f"{description} Déclarée par: {', '.join(row['employee_names'])}."
            )
        category = KNOWN_EXPENSE_CATEGORY_MAP.get(row["key"], "AUTRE")
        if entry:
            entry.category = category
            entry.funding_source = "CAISSE"
            entry.amount = row["amount"]
            entry.description = description
            entry.created_by = sync_owner
            entry.is_system_generated = True
            entry.system_source = DAILY_REPORT_SYNC_SOURCE
            entry.save(
                update_fields=[
                    "category",
                    "funding_source",
                    "amount",
                    "description",
                    "created_by",
                    "is_system_generated",
                    "system_source",
                    "updated_at",
                ]
            )
        else:
            SiteLossEntry.objects.create(
                site=site,
                date=target_date,
                category=category,
                funding_source="CAISSE",
                amount=row["amount"],
                title=title,
                description=description,
                created_by=sync_owner,
                is_system_generated=True,
                system_source=DAILY_REPORT_SYNC_SOURCE,
            )

    for title, entry in existing_loss_map.items():
        if title not in desired_titles:
            entry.delete()

    deposit_notes = (
        f"{AUTO_REPORT_DEPOSIT_NOTE} "
        f"Total déclaré: {reported_total:,.0f} FC. "
        f"Dépenses du jour: {daily_expenses_total:,.0f} FC."
    ).replace(",", " ")
    if auto_deposit:
        auto_deposit.amount = bank_deposit_amount
        auto_deposit.notes = deposit_notes
        auto_deposit.created_by = sync_owner
        auto_deposit.is_system_generated = True
        auto_deposit.system_source = DAILY_REPORT_SYNC_SOURCE
        auto_deposit.save(
            update_fields=[
                "amount",
                "notes",
                "created_by",
                "is_system_generated",
                "system_source",
                "updated_at",
            ]
        )
    else:
        DailyBankDeposit.objects.create(
            site=site,
            date=target_date,
            amount=bank_deposit_amount,
            notes=deposit_notes,
            created_by=sync_owner,
            is_system_generated=True,
            system_source=DAILY_REPORT_SYNC_SOURCE,
        )

    return {
        "reported_total": reported_total,
        "base_cash_flow": base_cash_flow,
        "adjustment_amount": adjustment_amount,
        "daily_expenses_total": daily_expenses_total,
        "bank_deposit_amount": bank_deposit_amount,
        "report_count": len(confirmed_shifts),
    }
