from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import Count, Max, Q
from django.utils import timezone

from comptes.models import AdminReminder, UserProfile
from pointage.models import ShiftDay


def _stamp_for_cache(value):
    if value is None:
        return "none"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def ensure_admin_profile(user):
    if not user.is_authenticated:
        return None

    profile = getattr(user, "userprofile", None)

    if user.is_superuser:
        if profile is None:
            now = timezone.now()
            profile = UserProfile.objects.create(
                user=user,
                role="ADMIN",
                admin_requests_last_seen_at=now,
                admin_reports_last_seen_at=now,
            )
        elif not profile.is_admin():
            profile.role = "ADMIN"
            profile.save(update_fields=["role", "updated_at"])

    return profile


def _get_admin_messages_unread_count(profile):
    if not profile:
        return 0

    last_seen = profile.admin_messages_last_seen_at
    today = timezone.localdate()

    active_manual_reminders = AdminReminder.objects.filter(is_resolved=False)
    employee_profiles = UserProfile.objects.filter(
        role="EMPLOYE",
        actif=True,
        user__is_active=True,
        site__actif=True,
        date_naissance__isnull=False,
    )
    reminder_meta = active_manual_reminders.aggregate(total=Count("id"), latest=Max("updated_at"))
    birthday_meta = employee_profiles.aggregate(total=Count("id"), latest=Max("updated_at"))
    cache_key = ":".join(
        [
            "admin-messages-unread-v2",
            str(profile.id),
            today.isoformat(),
            _stamp_for_cache(last_seen),
            str(reminder_meta["total"]),
            _stamp_for_cache(reminder_meta["latest"]),
            str(birthday_meta["total"]),
            _stamp_for_cache(birthday_meta["latest"]),
        ]
    )
    cached_value = cache.get(cache_key)
    if cached_value is not None:
        return cached_value

    if last_seen:
        unread_manual_reminders = active_manual_reminders.filter(
            Q(created_at__gt=last_seen) | Q(updated_at__gt=last_seen)
        ).count()
    else:
        unread_manual_reminders = reminder_meta["total"]

    unread_birthday_alerts = 0
    employee_profiles = (
        employee_profiles
        .select_related("site", "user")
        .only("id", "date_naissance", "updated_at", "site__actif", "user__is_active")
    )
    for employee_profile in employee_profiles:
        next_birthday = employee_profile.prochaine_date_anniversaire(today)
        if not next_birthday:
            continue
        days_until = (next_birthday - today).days
        if days_until < 0 or days_until > 30:
            continue

        alert_start_date = next_birthday - timedelta(days=30)
        alert_start = timezone.make_aware(
            datetime.combine(alert_start_date, time.min),
            timezone.get_current_timezone(),
        )
        event_time = max(alert_start, employee_profile.updated_at or alert_start)
        if last_seen is None or event_time > last_seen:
            unread_birthday_alerts += 1

    unread_total = unread_manual_reminders + unread_birthday_alerts
    cache.set(cache_key, unread_total, 300)
    return unread_total


def get_admin_inbox_counts(user):
    profile = ensure_admin_profile(user)
    if not user.is_authenticated:
        return {
            "show_admin_box": False,
            "admin_inbox_unread_requests": 0,
            "admin_inbox_unread_reports": 0,
            "admin_inbox_unread_total": 0,
            "admin_messages_unread_total": 0,
        }

    if not (user.is_superuser or (profile and profile.is_admin())):
        return {
            "show_admin_box": False,
            "admin_inbox_unread_requests": 0,
            "admin_inbox_unread_reports": 0,
            "admin_inbox_unread_total": 0,
            "admin_messages_unread_total": 0,
        }

    pending_requests_qs = User.objects.filter(
        is_active=False,
        is_superuser=False,
        userprofile__actif=False,
    )
    daily_reports_qs = ShiftDay.objects.filter(daily_report_confirmed=True)

    unread_messages = _get_admin_messages_unread_count(profile)
    pending_meta = pending_requests_qs.aggregate(total=Count("id"), latest=Max("date_joined"))
    reports_meta = daily_reports_qs.aggregate(total=Count("id"), latest=Max("updated_at"))
    cache_key = ":".join(
        [
            "admin-inbox-counts-v2",
            str(profile.id if profile else "none"),
            _stamp_for_cache(getattr(profile, "admin_requests_last_seen_at", None)),
            _stamp_for_cache(getattr(profile, "admin_reports_last_seen_at", None)),
            str(pending_meta["total"]),
            _stamp_for_cache(pending_meta["latest"]),
            str(reports_meta["total"]),
            _stamp_for_cache(reports_meta["latest"]),
            str(unread_messages),
        ]
    )
    cached_counts = cache.get(cache_key)
    if cached_counts is not None:
        return cached_counts

    unread_requests = 0
    unread_reports = 0

    if profile and profile.admin_requests_last_seen_at:
        if pending_meta["latest"] and pending_meta["latest"] > profile.admin_requests_last_seen_at:
            unread_requests = pending_requests_qs.filter(date_joined__gt=profile.admin_requests_last_seen_at).count()

    if profile and profile.admin_reports_last_seen_at:
        if reports_meta["latest"] and reports_meta["latest"] > profile.admin_reports_last_seen_at:
            unread_reports = daily_reports_qs.filter(updated_at__gt=profile.admin_reports_last_seen_at).count()

    counts_context = {
        "show_admin_box": True,
        "admin_inbox_unread_requests": unread_requests,
        "admin_inbox_unread_reports": unread_reports,
        "admin_inbox_unread_total": unread_requests + unread_reports,
        "admin_messages_unread_total": unread_messages,
    }
    cache.set(cache_key, counts_context, 120)
    return counts_context


def mark_admin_inbox_seen(user):
    profile = ensure_admin_profile(user)
    if not user.is_authenticated or not profile:
        return
    if not (user.is_superuser or profile.is_admin()):
        return

    now = timezone.now()
    profile.admin_requests_last_seen_at = now
    profile.admin_reports_last_seen_at = now
    profile.save(update_fields=["admin_requests_last_seen_at", "admin_reports_last_seen_at", "updated_at"])


def mark_admin_messages_seen(user):
    profile = ensure_admin_profile(user)
    if not user.is_authenticated or not profile:
        return
    if not (user.is_superuser or profile.is_admin()):
        return

    now = timezone.now()
    profile.admin_messages_last_seen_at = now
    profile.save(update_fields=["admin_messages_last_seen_at", "updated_at"])
