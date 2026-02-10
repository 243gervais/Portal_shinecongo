from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import IssueReport
from audit.models import AuditLog
from pointage.utils import get_client_ip, get_user_agent


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
