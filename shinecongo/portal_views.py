import json
import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie


PORTAL_FRONTEND_DIST_DIR = (
    Path(settings.BASE_DIR).resolve() / "frontend_dist" / "frontend"
)


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


def _portal_asset_version():
    asset_path = PORTAL_FRONTEND_DIST_DIR / "portal-app.js"
    try:
        return str(asset_path.stat().st_mtime_ns)
    except FileNotFoundError:
        return "dev"


def _render_portal_shell(request, mode):
    context = {
        "portal_mode": mode,
        "portal_asset_version": _portal_asset_version(),
        "portal_assets_base_url": "/portal-assets/",
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


def portal_frontend_asset(request, asset_path):
    requested_path = (PORTAL_FRONTEND_DIST_DIR / asset_path).resolve()
    try:
        requested_path.relative_to(PORTAL_FRONTEND_DIST_DIR)
    except ValueError as exc:
        raise Http404("Fichier introuvable.") from exc

    if not requested_path.is_file():
        raise Http404("Fichier introuvable.")

    content_type, _ = mimetypes.guess_type(requested_path.name)
    response = FileResponse(
        requested_path.open("rb"),
        content_type=content_type or "application/octet-stream",
    )
    if asset_path.startswith("assets/"):
        response["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response["Cache-Control"] = "public, max-age=300"
    return response


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
def employee_fuel_purchase_portal(request, *args, **kwargs):
    if request.method == "POST":
        from pointage.views import employe_fuel_purchase

        return employe_fuel_purchase(request, *args, **kwargs)
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
