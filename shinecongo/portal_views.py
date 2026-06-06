import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie


def _message_payloads(request):
    return [
        {
            "level": message.tags or "info",
            "text": str(message),
        }
        for message in request._messages
    ]


def _user_summary(user):
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.get_full_name() or user.username,
    }


def _render_portal_shell(request, mode):
    context = {
        "portal_mode": mode,
        "portal_bootstrap_json": json.dumps(
            {
                "mode": mode,
                "user": _user_summary(request.user),
                "messages": _message_payloads(request),
                "api_base": "/api/portal",
                "logout_url": "/logout/",
                "login_url": "/login/",
            }
        ),
    }
    return render(request, "portal/spa.html", context)


@login_required
@ensure_csrf_cookie
def employee_portal_shell(request, *args, **kwargs):
    profile = getattr(request.user, "userprofile", None)
    if not profile or not profile.is_employe() or not profile.site_id:
        return redirect("dashboard")
    return _render_portal_shell(request, "employee")


@login_required
@ensure_csrf_cookie
def manager_portal_shell(request, *args, **kwargs):
    if request.user.is_superuser:
        return _render_portal_shell(request, "manager")

    profile = getattr(request.user, "userprofile", None)
    if not profile or not (profile.is_manager() or profile.is_admin()):
        return redirect("dashboard")
    return _render_portal_shell(request, "manager")


@login_required
@ensure_csrf_cookie
def employee_water_purchase_portal(request, *args, **kwargs):
    if request.method == "POST":
        from pointage.views import employe_water_purchase

        return employe_water_purchase(request, *args, **kwargs)
    return employee_portal_shell(request, *args, **kwargs)


@login_required
@ensure_csrf_cookie
def employee_daily_report_portal(request, *args, **kwargs):
    if request.method == "POST":
        from pointage.views import employe_daily_report

        return employe_daily_report(request, *args, **kwargs)
    return employee_portal_shell(request, *args, **kwargs)


@login_required
@ensure_csrf_cookie
def employee_add_wash_portal(request, *args, **kwargs):
    if request.method == "POST":
        from lavages.views import ajouter_lavage

        return ajouter_lavage(request, *args, **kwargs)
    return employee_portal_shell(request, *args, **kwargs)


@login_required
@ensure_csrf_cookie
def employee_issue_portal(request, *args, **kwargs):
    if request.method == "POST":
        from problemes.views import signaler_probleme

        return signaler_probleme(request, *args, **kwargs)
    return employee_portal_shell(request, *args, **kwargs)


@login_required
@ensure_csrf_cookie
def manager_pointage_correction_portal(request, *args, **kwargs):
    if request.method == "POST":
        from pointage.views_manager import manager_corriger_pointage

        return manager_corriger_pointage(request, *args, **kwargs)
    return manager_portal_shell(request, *args, **kwargs)
