from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib import messages
from .models import CarWash, CarWashPhoto
from audit.models import AuditLog
from pointage.utils import get_client_ip, get_user_agent


@login_required
def ajouter_lavage(request):
    """
    Ajouter un nouveau lavage
    """
    if request.method == 'POST':
        try:
            user = request.user
            site = user.userprofile.site
            
            # Récupérer les données du formulaire
            type_service = request.POST.get('type_service')
            plaque = request.POST.get('plaque', '')
            montant = request.POST.get('montant')
            notes = request.POST.get('notes', '')
            
            # Créer le lavage
            lavage = CarWash.objects.create(
                employe=user,
                site=site,
                date=timezone.localdate(),
                type_service=type_service,
                plaque=plaque,
                montant=montant,
                notes=notes
            )
            
            # Traiter les photos
            photos = request.FILES.getlist('photos')
            for idx, photo in enumerate(photos):
                # Déterminer le type (avant/après/autre)
                type_photo = 'AVANT' if idx == 0 else 'APRES' if idx == 1 else 'AUTRE'
                
                CarWashPhoto.objects.create(
                    lavage=lavage,
                    photo=photo,
                    type_photo=type_photo
                )
            
            # Log d'audit
            AuditLog.log(
                user=user,
                action="CREER",
                description=f"Nouveau lavage: {lavage}",
                content_object=lavage,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )
            
            messages.success(request, 'Lavage enregistré avec succès !')
            return redirect('employe_dashboard')
            
        except Exception as e:
            messages.error(request, f'Erreur lors de l\'enregistrement: {str(e)}')
    
    return render(request, 'employe/ajouter_lavage.html', {
        'types_service': CarWash.TYPE_SERVICE_CHOICES
    })


@login_required
def mes_lavages(request):
    """
    Liste des lavages de l'employé
    """
    user = request.user
    lavages = user.lavages.all().order_by('-created_at').prefetch_related('photos')
    
    # L'employé ne doit PAS voir les totaux d'argent
    # On affiche juste la liste
    
    context = {
        'lavages': lavages,
    }
    
    return render(request, 'employe/mes_lavages.html', context)


@login_required
def detail_lavage(request, lavage_id):
    """
    Détail d'un lavage (avec photos)
    """
    lavage = get_object_or_404(CarWash, id=lavage_id, employe=request.user)
    
    context = {
        'lavage': lavage,
        'photos': lavage.photos.all()
    }
    
    return render(request, 'employe/detail_lavage.html', context)
