from django.contrib.auth.models import User
from django.utils import timezone

from comptes.models import UserProfile
from pointage.models import ShiftDay


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


def get_admin_inbox_counts(user):
    profile = ensure_admin_profile(user)
    if not user.is_authenticated:
        return {
            "show_admin_box": False,
            "admin_inbox_unread_requests": 0,
            "admin_inbox_unread_reports": 0,
            "admin_inbox_unread_total": 0,
        }

    if not (user.is_superuser or (profile and profile.is_admin())):
        return {
            "show_admin_box": False,
            "admin_inbox_unread_requests": 0,
            "admin_inbox_unread_reports": 0,
            "admin_inbox_unread_total": 0,
        }

    pending_requests_qs = User.objects.filter(
        is_active=False,
        is_superuser=False,
        userprofile__actif=False,
    )
    daily_reports_qs = ShiftDay.objects.filter(daily_report_confirmed=True)

    unread_requests = 0
    unread_reports = 0

    if profile and profile.admin_requests_last_seen_at:
        unread_requests = pending_requests_qs.filter(date_joined__gt=profile.admin_requests_last_seen_at).count()

    if profile and profile.admin_reports_last_seen_at:
        unread_reports = daily_reports_qs.filter(updated_at__gt=profile.admin_reports_last_seen_at).count()

    return {
        "show_admin_box": True,
        "admin_inbox_unread_requests": unread_requests,
        "admin_inbox_unread_reports": unread_reports,
        "admin_inbox_unread_total": unread_requests + unread_reports,
    }


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
