import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404

from .models import IssueReport
from audit.models import AuditLog
from pointage.utils import get_client_ip, get_user_agent

logger = logging.getLogger(__name__)


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

    reporter_name = (
        probleme.employe.get_full_name() or probleme.employe.username
        if probleme.employe_id else
        "Employé non précisé"
    )
    subject = (
        f"Problème signalé - "
        f"{probleme.site.nom} - {probleme.created_at.strftime('%d/%m/%Y')}"
    )
    message = "\n".join([
        f"Employé: {reporter_name}",
        f"Site: {probleme.site.nom}",
        f"Date: {probleme.created_at.strftime('%d/%m/%Y %H:%M')}",
        f"Catégorie: {probleme.get_categorie_display()}",
        f"Statut: {probleme.get_statut_display()}",
        "",
        f"Description: {probleme.description}",
    ])

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[recipient],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Impossible d'envoyer la notification email du problème signalé")
        return False


@login_required
def signaler_probleme(request):
    """
    Signaler un nouveau problème
    """
    if request.method == 'POST':
        try:
            user = request.user
            site = user.userprofile.site
            
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
            return redirect('employe_dashboard')
            
        except Exception as e:
            messages.error(request, f'Erreur lors du signalement: {str(e)}')
    
    return render(request, 'employe/signaler_probleme.html', {
        'categories': IssueReport.CATEGORIE_CHOICES
    })


@login_required
def mes_problemes(request):
    """
    Liste des problèmes signalés par l'employé
    """
    user = request.user
    problemes = user.problemes_signales.all().order_by('-created_at')
    
    context = {
        'problemes': problemes,
    }
    
    return render(request, 'employe/mes_problemes.html', context)


@login_required
def detail_probleme(request, probleme_id):
    """
    Détail d'un problème
    """
    probleme = get_object_or_404(
        IssueReport,
        id=probleme_id,
        employe=request.user
    )
    
    context = {
        'probleme': probleme,
    }
    
    return render(request, 'employe/detail_probleme.html', context)
