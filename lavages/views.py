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
            
            # Vérifier que l'utilisateur a un profil et un site assigné
            if not hasattr(user, 'userprofile'):
                messages.error(request, 'Erreur: Votre profil utilisateur n\'existe pas. Veuillez contacter l\'administrateur.')
                return render(request, 'employe/ajouter_lavage.html', {
                    'types_service': CarWash.TYPE_SERVICE_CHOICES
                })
            
            site = user.userprofile.site
            if not site:
                messages.error(request, 'Erreur: Aucun site n\'est assigné à votre compte. Veuillez contacter votre manager ou l\'administrateur pour assigner un site.')
                return render(request, 'employe/ajouter_lavage.html', {
                    'types_service': CarWash.TYPE_SERVICE_CHOICES
                })
            
            # Récupérer les données du formulaire
            type_service = request.POST.get('type_service')
            plaque = request.POST.get('plaque', '')
            montant = request.POST.get('montant')
            notes = request.POST.get('notes', '')
            
            # Validation des champs requis
            if not type_service:
                messages.error(request, 'Le type de service est requis.')
                return render(request, 'employe/ajouter_lavage.html', {
                    'types_service': CarWash.TYPE_SERVICE_CHOICES
                })
            
            if not montant:
                messages.error(request, 'Le montant est requis.')
                return render(request, 'employe/ajouter_lavage.html', {
                    'types_service': CarWash.TYPE_SERVICE_CHOICES
                })
            
            # Vérifier qu'il y a au moins une photo
            photos = request.FILES.getlist('photos')
            if not photos:
                messages.error(request, 'Au moins une photo est requise.')
                return render(request, 'employe/ajouter_lavage.html', {
                    'types_service': CarWash.TYPE_SERVICE_CHOICES
                })
            
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
            
            # Traiter les photos (toutes marquées comme "après lavage")
            for photo in photos:
                CarWashPhoto.objects.create(
                    lavage=lavage,
                    photo=photo,
                    type_photo='APRES'  # Toutes les photos sont après lavage
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
