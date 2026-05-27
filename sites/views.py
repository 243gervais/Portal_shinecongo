import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.cache import never_cache

from audit.models import AuditLog
from comptes.models import UserProfile
from pointage.utils import get_client_ip, get_user_agent

from .forms import CameraObservationForm, CameraOperatorDailyReportFinalForm
from .models import (
    CameraObservation,
    CameraObservationEvidence,
    CameraOperatorDailyReport,
    Location,
)

logger = logging.getLogger(__name__)


def _is_camera_controller(user):
    profile = getattr(user, "userprofile", None)
    return bool(profile and profile.is_camera_controller())


def _is_admin_user(user):
    profile = getattr(user, "userprofile", None)
    return bool(user.is_superuser or (profile and profile.is_admin()))


def _resolve_camera_controller_profile(request):
    profile = getattr(request.user, "userprofile", None)
    if not profile or not profile.is_camera_controller():
        messages.error(request, "Accès refusé. Ce portail est réservé aux contrôleurs caméra.")
        return None
    if not profile.site:
        messages.error(request, "Aucun site n'est associé à votre compte caméra.")
        return None
    return profile


def _build_camera_dashboard_context(user, site):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    month_reports_qs = CameraOperatorDailyReport.objects.filter(
        controller=user,
        site=site,
        date__gte=month_start,
        date__lte=today,
    )
    today_report = month_reports_qs.filter(date=today).first()
    recent_reports = list(
        CameraOperatorDailyReport.objects.filter(controller=user, site=site, is_submitted=True)
        .order_by("-date", "-submitted_at")[:8]
    )

    return {
        "site": site,
        "today": today,
        "today_report": today_report,
        "today_observations_count": today_report.observations.count() if today_report else 0,
        "today_screenshots_count": today_report.screenshots_count if today_report else 0,
        "month_reports_count": month_reports_qs.filter(is_submitted=True).count(),
        "month_vehicles_count": sum(item.total_vehicles for item in month_reports_qs if item.is_submitted),
        "month_screenshots_count": sum(item.screenshots_count for item in month_reports_qs),
        "recent_reports": recent_reports,
    }


def _build_camera_final_report_email_context(report, was_update):
    controller_name = report.controller.get_full_name() or report.controller.username
    notes = (report.notes or "").strip()

    return {
        "company_name": "Shine Congo",
        "controller_name": controller_name,
        "site_name": report.site.nom,
        "report_date": report.date,
        "submitted_at": timezone.localtime(report.submitted_at or timezone.now()),
        "action_label": "mis à jour" if was_update else "soumis",
        "action_copy": "Rapport final mis à jour" if was_update else "Rapport final envoyé",
        "cars_count": report.cars_count,
        "motos_count": report.motos_count,
        "three_wheelers_count": report.three_wheelers_count,
        "total_vehicles": report.total_vehicles,
        "screenshots_count": report.screenshots_count,
        "notes": notes or "Aucune note",
        "has_notes": bool(notes),
    }


def _send_camera_final_report_notification(report, was_update):
    recipient = (getattr(settings, "FINAL_REPORT_NOTIFICATION_EMAIL", "") or "").strip()
    if not recipient:
        return False

    email_backend = getattr(settings, "EMAIL_BACKEND", "")
    uses_smtp_backend = email_backend.endswith("smtp.EmailBackend")
    if uses_smtp_backend and (
        not getattr(settings, "EMAIL_HOST", "")
        or not getattr(settings, "EMAIL_HOST_USER", "")
        or not getattr(settings, "EMAIL_HOST_PASSWORD", "")
    ):
        logger.warning(
            "Notification email skipped for camera final report because SMTP settings are incomplete"
        )
        return False

    context = _build_camera_final_report_email_context(report, was_update)
    subject = (
        f"Rapport final caméra {context['action_label']} - "
        f"{report.site.nom} - {report.date.strftime('%d/%m/%Y')}"
    )
    message = render_to_string("emails/camera_final_report_notification.txt", context)
    html_message = render_to_string("emails/camera_final_report_notification.html", context)

    try:
        email_message = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=[recipient],
        )
        email_message.attach_alternative(html_message, "text/html")
        email_message.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("Impossible d'envoyer la notification email du rapport final caméra")
        return False


@login_required
@never_cache
def camera_dashboard(request):
    profile = _resolve_camera_controller_profile(request)
    if not profile:
        return redirect("dashboard")

    context = _build_camera_dashboard_context(request.user, profile.site)
    return render(request, "camera/dashboard.html", context)


@login_required
@never_cache
def camera_daily_report(request):
    profile = _resolve_camera_controller_profile(request)
    if not profile:
        return redirect("dashboard")

    site = profile.site
    today = timezone.localdate()
    report, _created = CameraOperatorDailyReport.objects.get_or_create(
        site=site,
        controller=request.user,
        date=today,
    )
    report.sync_observation_totals()

    observation_form = CameraObservationForm(site=site)
    final_form = CameraOperatorDailyReportFinalForm(instance=report)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "add_observation":
            observation_form = CameraObservationForm(request.POST, request.FILES, site=site)
            if observation_form.is_valid():
                observation = CameraObservation.objects.create(
                    report=report,
                    vehicle_type=observation_form.cleaned_data["vehicle_type"],
                    plate_number=observation_form.cleaned_data["plate_number"],
                    observed_time=observation_form.cleaned_data["observed_time"],
                    notes=observation_form.cleaned_data["notes"],
                )
                for screenshot in observation_form.cleaned_data["screenshots"]:
                    CameraObservationEvidence.objects.create(
                        observation=observation,
                        evidence_kind=CameraObservationEvidence.KIND_SCREENSHOT,
                        file=screenshot,
                    )

                AuditLog.log(
                    user=request.user,
                    action="CREER",
                    description=(
                        f"Vérification lavage ajoutée sur {site.nom}: "
                        f"{observation.get_vehicle_type_display()}"
                        f"{f' - {observation.plate_number}' if observation.plate_number else ''} "
                        f"par contrôleur caméra"
                    ),
                    content_object=observation,
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request),
                )
                messages.success(request, "Vérification lavage enregistrée. Le compteur du jour a été mis à jour.")
                if report.is_submitted:
                    messages.info(
                        request,
                        "Le rapport final était déjà soumis. Soumettez-le à nouveau pour actualiser la version de fin de journée.",
                    )
                return redirect("camera_lavage_verification")

        elif action == "submit_final_report":
            final_form = CameraOperatorDailyReportFinalForm(request.POST, instance=report)
            if final_form.is_valid():
                report.sync_observation_totals()
                if report.total_vehicles <= 0:
                    messages.error(request, "Ajoutez au moins une observation avant de soumettre le rapport final.")
                else:
                    was_update = report.is_submitted
                    report = final_form.save(commit=False)
                    report.is_submitted = True
                    report.submitted_at = timezone.now()
                    report.save(update_fields=["notes", "is_submitted", "submitted_at", "updated_at"])
                    _send_camera_final_report_notification(report, was_update)
                    AuditLog.log(
                        user=request.user,
                        action="CREER",
                        description=f"Rapport final caméra soumis sur {site.nom} pour le {today:%d/%m/%Y}",
                        content_object=report,
                        ip_address=get_client_ip(request),
                        user_agent=get_user_agent(request),
                    )
                    messages.success(request, "Rapport final caméra soumis avec succès.")
                    return redirect("camera_lavage_verification")

    observations = list(
        report.observations.select_related("camera").prefetch_related("evidences").order_by("-created_at")
    )
    week_start = today - timedelta(days=today.weekday())
    weekly_reports = list(
        CameraOperatorDailyReport.objects.filter(
            controller=request.user,
            site=site,
            date__gte=week_start,
            date__lte=today,
            is_submitted=True,
        ).order_by("-date")
    )

    context = {
        "site": site,
        "today": today,
        "report": report,
        "observations": observations,
        "observation_form": observation_form,
        "final_form": final_form,
        "weekly_reports": weekly_reports,
    }
    return render(request, "camera/daily_report.html", context)


@login_required
@never_cache
def camera_delete_observation(request, observation_id):
    profile = _resolve_camera_controller_profile(request)
    if not profile:
        return redirect("dashboard")

    observation = get_object_or_404(
        CameraObservation.objects.select_related("report", "camera"),
        id=observation_id,
        report__controller=request.user,
        report__site=profile.site,
    )

    if request.method == "POST":
        for evidence in observation.evidences.all():
            if evidence.file:
                evidence.file.delete(save=False)
        vehicle_label = observation.get_vehicle_type_display()
        observation.delete()

        AuditLog.log(
            user=request.user,
            action="SUPPRIMER",
            description=f"Observation caméra supprimée sur {profile.site.nom}: {vehicle_label}",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        messages.success(request, "Observation supprimée.")

    return redirect("camera_lavage_verification")


@login_required
@never_cache
def admin_camera_operator_report_detail(request, site_id, report_id):
    if not _is_admin_user(request.user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    report = get_object_or_404(
        CameraOperatorDailyReport.objects.select_related("controller", "controller__userprofile", "site").prefetch_related(
            "observations__camera",
            "observations__evidences",
        ),
        id=report_id,
        site=site,
    )
    observations = list(report.observations.all().order_by("-created_at"))

    context = {
        "site": site,
        "report": report,
        "observations": observations,
    }
    return render(request, "admin/camera_operator_report_detail.html", context)
