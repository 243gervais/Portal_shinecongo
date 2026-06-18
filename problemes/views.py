import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import IssueReport
from audit.models import AuditLog
from comptes.pagination import paginate_queryset
from pointage.utils import get_client_ip, get_user_agent

logger = logging.getLogger(__name__)


def _resolve_employee_portal_profile(request):
    profile = getattr(request.user, "userprofile", None)
    if not profile or not profile.is_employe():
        messages.error(request, "Accès refusé. Ce portail est réservé aux employés lavage.")
        return None
    if not profile.site:
        messages.error(request, "Aucun site n'est associé à votre profil.")
        return None
    return profile


def _resolve_issue_portal_profile(request):
    profile = getattr(request.user, "userprofile", None)
    if not profile:
        messages.error(request, "Accès refusé. Aucun profil employé n'est associé à ce compte.")
        return None, None

    if profile.is_employe():
        portal_variant = "employee"
    elif profile.is_camera_controller():
        portal_variant = "camera"
    else:
        messages.error(
            request,
            "Accès refusé. Ce formulaire est réservé aux employés lavage et aux contrôleurs caméra.",
        )
        return None, None

    if not profile.site:
        messages.error(request, "Aucun site n'est associé à votre profil.")
        return None, None

    return profile, portal_variant


def _issue_portal_context(profile, portal_variant):
    if portal_variant == "camera":
        return {
            "portal_variant": portal_variant,
            "page_title": "Signaler un problème caméra",
            "page_intro": (
                "Déclarez ici tout problème constaté pendant la journée: matériel, sécurité, client, "
                "eau ou toute autre anomalie observée depuis le portail contrôle caméra."
            ),
            "submit_label": "Envoyer le signalement",
            "cancel_url": reverse("camera_dashboard"),
            "cancel_label": "Retour au portail caméra",
            "success_redirect": "camera_dashboard",
        }

    return {
        "portal_variant": portal_variant,
        "page_title": "Signaler un problème",
        "page_intro": "Décrivez le problème rencontré pendant votre journée de travail.",
        "submit_label": "Signaler le problème",
        "cancel_url": reverse("employe_dashboard"),
        "cancel_label": "Annuler",
        "success_redirect": "employe_dashboard",
    }


def _build_issue_report_email_context(probleme):
    reporter_name = (
        probleme.employe.get_full_name() or probleme.employe.username
        if probleme.employe_id else
        "Employé non précisé"
    )

    return {
        "company_name": "Shine Congo",
        "reporter_name": reporter_name,
        "site_name": probleme.site.nom,
        "reported_at": timezone.localtime(probleme.created_at or timezone.now()),
        "category_label": probleme.get_categorie_display(),
        "status_label": probleme.get_statut_display(),
        "description": probleme.description,
        "has_photo": bool(probleme.photo),
    }


def _send_issue_report_notification(probleme):
    recipient = (
        getattr(settings, "ISSUE_REPORT_NOTIFICATION_EMAIL", "")
        or getattr(settings, "WATER_PURCHASE_NOTIFICATION_EMAIL", "")
        or getattr(settings, "FINAL_REPORT_NOTIFICATION_EMAIL", "")
        or ""
    ).strip()
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
            "Notification email skipped for issue report because SMTP settings are incomplete"
        )
        return False

    context = _build_issue_report_email_context(probleme)
    subject = (
        f"Problème signalé - "
        f"{probleme.site.nom} - {probleme.created_at.strftime('%d/%m/%Y')}"
    )
    message = render_to_string("emails/issue_report_notification.txt", context)
    html_message = render_to_string("emails/issue_report_notification.html", context)

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
        logger.exception("Impossible d'envoyer la notification email du problème signalé")
        return False


@login_required
def signaler_probleme(request):
    """
    Signaler un nouveau problème
    """
    profile, portal_variant = _resolve_issue_portal_profile(request)
    if not profile:
        return redirect("dashboard")
    portal_context = _issue_portal_context(profile, portal_variant)

    if request.method == 'POST':
        try:
            user = request.user
            site = profile.site
            
            categorie = request.POST.get('categorie')
            description = request.POST.get('description')
            photo = request.FILES.get('photo')  # Optionnel
            
            probleme = IssueReport.objects.create(
                employe=user,
                site=site,
                categorie=categorie,
                description=description,
                photo=photo,
                statut='OUVERT'
            )
            _send_issue_report_notification(probleme)
            
            # Log d'audit
            AuditLog.log(
                user=user,
                action="CREER",
                description=f"Nouveau problème signalé: {probleme.get_categorie_display()}",
                content_object=probleme,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )
            
            messages.success(request, 'Problème signalé avec succès !')
            return redirect(portal_context["success_redirect"])
            
        except Exception as e:
            messages.error(request, f'Erreur lors du signalement: {str(e)}')
    
    return render(request, 'employe/signaler_probleme.html', {
        'categories': IssueReport.CATEGORIE_CHOICES,
        **portal_context,
    })


@login_required
def mes_problemes(request):
    """
    Liste des problèmes signalés par l'employé
    """
    profile = _resolve_employee_portal_profile(request)
    if not profile:
        return redirect("dashboard")
    user = request.user
    problemes_qs = user.problemes_signales.select_related("site", "traite_par").order_by("-created_at")
    problemes = paginate_queryset(request, problemes_qs, per_page=12, page_param="page")
    
    context = {
        'problemes': problemes,
    }
    
    return render(request, 'employe/mes_problemes.html', context)


@login_required
def detail_probleme(request, probleme_id):
    """
    Détail d'un problème
    """
    profile = _resolve_employee_portal_profile(request)
    if not profile:
        return redirect("dashboard")
    probleme = get_object_or_404(
        IssueReport.objects.select_related("site", "employe", "traite_par"),
        id=probleme_id,
        employe=request.user
    )
    
    context = {
        'probleme': probleme,
    }
    
    return render(request, 'employe/detail_probleme.html', context)
