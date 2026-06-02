import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from audit.models import AuditLog
from comptes.models import UserProfile
from pointage.utils import get_client_ip, get_user_agent

from .forms import AdminCameraObservationForm, CameraObservationForm, CameraOperatorDailyReportFinalForm
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
        "expected_revenue": report.expected_revenue,
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


def _build_camera_final_report_preview(report, notes_value):
    cleaned_notes = (notes_value or "").strip()
    is_update = bool(report.is_submitted)

    return {
        "action_label": "mise à jour" if is_update else "envoi",
        "action_copy": "mettre à jour" if is_update else "envoyer",
        "status_label": "Rapport déjà soumis" if is_update else "Prêt pour l'envoi",
        "total_vehicles": report.total_vehicles,
        "cars_count": report.cars_count,
        "motos_count": report.motos_count,
        "three_wheelers_count": report.three_wheelers_count,
        "screenshots_count": report.screenshots_count,
        "notes_value": notes_value or "",
        "notes_display": cleaned_notes or "Aucune note",
        "has_notes": bool(cleaned_notes),
    }


def _parse_admin_camera_report_date(request, fallback_date=None):
    raw_value = request.GET.get("date") or request.POST.get("selected_date")
    if raw_value:
        try:
            return datetime.strptime(raw_value, "%Y-%m-%d").date()
        except ValueError:
            pass
    return fallback_date or timezone.localdate()


def _camera_controller_admin_portal_url(site, controller_profile, report_date):
    base_url = reverse(
        "admin_camera_controller_portal",
        kwargs={"site_id": site.id, "profile_id": controller_profile.id},
    )
    if report_date:
        return f"{base_url}?date={report_date:%Y-%m-%d}"
    return base_url


def _camera_observation_form_initial(observation):
    return {
        "camera": observation.camera_id,
        "vehicle_type": observation.vehicle_type,
        "plate_number": observation.plate_number,
        "observed_time": observation.observed_time,
        "notes": observation.notes,
    }


def _build_admin_camera_controller_portal_context(
    request,
    site,
    controller_profile,
    report_date,
    report,
    observation_form=None,
    final_form=None,
    final_report_preview=None,
    editing_observation=None,
):
    controller_user = controller_profile.user
    observations = []
    if report.pk:
        observations = list(
            report.observations.select_related("camera").prefetch_related("evidences").order_by("-created_at")
        )

    history_queryset = (
        CameraObservation.objects.filter(
            report__controller=controller_user,
            report__site=site,
        )
        .exclude(report__date=report_date)
        .select_related("report", "camera")
        .prefetch_related("evidences")
        .order_by("-report__date", "-created_at")
    )
    verification_history = list(history_queryset[:18])

    week_start = report_date - timedelta(days=report_date.weekday())
    week_end = week_start + timedelta(days=6)
    weekly_reports = list(
        CameraOperatorDailyReport.objects.filter(
            controller=controller_user,
            site=site,
            date__gte=week_start,
            date__lte=week_end,
            is_submitted=True,
        ).order_by("-date", "-submitted_at")
    )

    if observation_form is None:
        initial = _camera_observation_form_initial(editing_observation) if editing_observation else None
        observation_form = AdminCameraObservationForm(site=site, initial=initial)
    if final_form is None:
        final_form = CameraOperatorDailyReportFinalForm(instance=report)

    page_base_url = reverse(
        "admin_camera_controller_portal",
        kwargs={"site_id": site.id, "profile_id": controller_profile.id},
    )
    page_url = _camera_controller_admin_portal_url(site, controller_profile, report_date)

    return {
        "site": site,
        "controller_profile": controller_profile,
        "controller_user": controller_user,
        "report": report,
        "selected_date": report_date,
        "observations": observations,
        "observation_form": observation_form,
        "editing_observation": editing_observation,
        "final_form": final_form,
        "final_report_preview": final_report_preview,
        "verification_history": verification_history,
        "weekly_reports": weekly_reports,
        "page_base_url": page_base_url,
        "page_url": page_url,
    }


def _admin_camera_controller_portal_response(request, site, controller_profile, report_date):
    controller_user = controller_profile.user
    existing_report = CameraOperatorDailyReport.objects.filter(
        site=site,
        controller=controller_user,
        date=report_date,
    ).first()
    report = existing_report or CameraOperatorDailyReport(
        site=site,
        controller=controller_user,
        date=report_date,
    )
    if report.pk:
        report.sync_observation_totals()

    page_url = _camera_controller_admin_portal_url(site, controller_profile, report_date)
    observation_form = None
    final_form = None
    final_report_preview = None
    editing_observation = None

    edit_observation_id = (request.GET.get("edit_observation") or "").strip()
    if request.method == "GET" and edit_observation_id and report.pk:
        editing_observation = get_object_or_404(
            CameraObservation.objects.select_related("camera", "report"),
            id=edit_observation_id,
            report=report,
        )

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "save_observation":
            observation_id = (request.POST.get("observation_id") or "").strip()
            if observation_id:
                editing_observation = get_object_or_404(
                    CameraObservation.objects.select_related("camera", "report"),
                    id=observation_id,
                    report__site=site,
                    report__controller=controller_user,
                    report__date=report_date,
                )

            observation_form = AdminCameraObservationForm(request.POST, request.FILES, site=site)
            if observation_form.is_valid():
                if not report.pk:
                    report.save()
                observation_data = observation_form.cleaned_data

                if editing_observation:
                    observation = editing_observation
                    observation.camera = observation_data["camera"]
                    observation.vehicle_type = observation_data["vehicle_type"]
                    observation.plate_number = observation_data["plate_number"]
                    observation.observed_time = observation_data["observed_time"]
                    observation.notes = observation_data["notes"]
                    observation.save()
                else:
                    observation = CameraObservation.objects.create(
                        report=report,
                        camera=observation_data["camera"],
                        vehicle_type=observation_data["vehicle_type"],
                        plate_number=observation_data["plate_number"],
                        observed_time=observation_data["observed_time"],
                        notes=observation_data["notes"],
                    )

                for screenshot in observation_data["screenshots"]:
                    CameraObservationEvidence.objects.create(
                        observation=observation,
                        evidence_kind=CameraObservationEvidence.KIND_SCREENSHOT,
                        file=screenshot,
                    )

                AuditLog.log(
                    user=request.user,
                    action="MODIFIER" if editing_observation else "CREER",
                    description=(
                        f"{'Correction' if editing_observation else 'Observation'} caméra admin sur {site.nom} "
                        f"pour {controller_user.get_full_name() or controller_user.username} "
                        f"le {report_date:%d/%m/%Y}: {observation.get_vehicle_type_display()}"
                    ),
                    content_object=observation,
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request),
                )
                messages.success(
                    request,
                    "Vérification contrôleur mise à jour." if editing_observation else "Vérification ajoutée au rapport contrôleur.",
                )
                if report.is_submitted:
                    messages.info(
                        request,
                        "Le rapport final était déjà soumis. Confirmez à nouveau la clôture pour renvoyer la version corrigée.",
                    )
                return redirect(f"{page_url}#controller-observations")

        elif action == "delete_observation" and report.pk:
            observation = get_object_or_404(
                CameraObservation.objects.select_related("report", "camera"),
                id=request.POST.get("observation_id"),
                report=report,
            )
            for evidence in observation.evidences.all():
                if evidence.file:
                    evidence.file.delete(save=False)
            vehicle_label = observation.get_vehicle_type_display()
            observation.delete()

            AuditLog.log(
                user=request.user,
                action="SUPPRIMER",
                description=(
                    f"Observation caméra supprimée par admin sur {site.nom} "
                    f"pour {controller_user.get_full_name() or controller_user.username}: {vehicle_label}"
                ),
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )
            messages.success(request, "Vérification supprimée du rapport contrôleur.")
            if report.is_submitted:
                messages.info(
                    request,
                    "Le rapport final reste marqué comme soumis. Confirmez à nouveau la clôture pour envoyer la version corrigée.",
                )
            return redirect(f"{page_url}#controller-observations")

        elif action == "preview_final_report":
            final_form = CameraOperatorDailyReportFinalForm(request.POST, instance=report)
            if report.pk:
                report.sync_observation_totals()
            if report.total_vehicles <= 0:
                messages.error(request, "Ajoutez au moins une observation avant de finaliser ce rapport contrôleur.")
            elif final_form.is_valid():
                final_report_preview = _build_camera_final_report_preview(
                    report,
                    final_form.cleaned_data["notes"],
                )

        elif action == "confirm_final_report":
            final_form = CameraOperatorDailyReportFinalForm(request.POST, instance=report)
            if report.pk:
                report.sync_observation_totals()
            if report.total_vehicles <= 0:
                messages.error(request, "Ajoutez au moins une observation avant de finaliser ce rapport contrôleur.")
            elif final_form.is_valid():
                was_update = report.is_submitted
                report = final_form.save(commit=False)
                report.is_submitted = True
                report.submitted_at = timezone.now()
                report.save(update_fields=["notes", "is_submitted", "submitted_at", "updated_at"])
                _send_camera_final_report_notification(report, was_update)
                AuditLog.log(
                    user=request.user,
                    action="MODIFIER" if was_update else "CREER",
                    description=(
                        f"Rapport final caméra {'mis à jour' if was_update else 'soumis'} par admin sur {site.nom} "
                        f"pour {controller_user.get_full_name() or controller_user.username} "
                        f"le {report_date:%d/%m/%Y}"
                    ),
                    content_object=report,
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request),
                )
                messages.success(
                    request,
                    "Rapport final caméra mis à jour avec succès." if was_update else "Rapport final caméra soumis avec succès.",
                )
                return redirect(f"{page_url}#final-report-form")

    context = _build_admin_camera_controller_portal_context(
        request,
        site,
        controller_profile,
        report_date,
        report,
        observation_form=observation_form,
        final_form=final_form,
        final_report_preview=final_report_preview,
        editing_observation=editing_observation,
    )
    return render(request, "admin/camera_operator_report_detail.html", context)


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
    final_report_preview = None

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

        elif action == "preview_final_report":
            final_form = CameraOperatorDailyReportFinalForm(request.POST, instance=report)
            if final_form.is_valid():
                report.sync_observation_totals()
                if report.total_vehicles <= 0:
                    messages.error(request, "Ajoutez au moins une observation avant de soumettre le rapport final.")
                else:
                    final_report_preview = _build_camera_final_report_preview(
                        report,
                        final_form.cleaned_data["notes"],
                    )

        elif action == "confirm_final_report":
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
    verification_history = list(
        CameraObservation.objects.filter(
            report__controller=request.user,
            report__site=site,
        )
        .exclude(report=report)
        .select_related("report", "camera")
        .prefetch_related("evidences")
        .order_by("-report__date", "-created_at")[:18]
    )

    context = {
        "site": site,
        "today": today,
        "report": report,
        "observations": observations,
        "observation_form": observation_form,
        "final_form": final_form,
        "final_report_preview": final_report_preview,
        "verification_history": verification_history,
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
    controller_profile = getattr(report.controller, "userprofile", None)
    if not controller_profile:
        messages.error(request, "Le contrôleur caméra lié à ce rapport est introuvable.")
        return redirect("admin_site_camera_monitoring", site_id=site.id)
    return _admin_camera_controller_portal_response(request, site, controller_profile, report.date)


@login_required
@never_cache
def admin_camera_controller_portal(request, site_id, profile_id):
    if not _is_admin_user(request.user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    controller_profile = get_object_or_404(
        UserProfile.objects.select_related("user"),
        id=profile_id,
        site=site,
        role=UserProfile.CAMERA_CONTROLLER_ROLE,
    )
    report_date = _parse_admin_camera_report_date(request)
    return _admin_camera_controller_portal_response(request, site, controller_profile, report_date)
