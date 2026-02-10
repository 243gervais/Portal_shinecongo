from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.conf import settings
from .models import ShiftDay
from sites.models import Location
from .utils import generate_qr_code_image, get_client_ip, get_user_agent
from lavages.models import CarWash
from problemes.models import IssueReport
from comptes.models import UserProfile
from audit.models import AuditLog
from django.contrib.auth.models import User


def is_manager_or_admin(user):
    """Vérifier que l'utilisateur est manager ou admin"""
    if not hasattr(user, 'userprofile'):
        return False
    return user.userprofile.is_manager() or user.userprofile.is_admin()


@login_required
@user_passes_test(is_manager_or_admin)
def manager_dashboard(request):
    """
    Dashboard principal pour les managers
    """
    user = request.user
    today = timezone.localdate()
    
    # Déterminer les sites du manager
    if user.userprofile.is_admin():
        # Admin voit tous les sites
        from sites.models import Location
        sites = Location.objects.filter(actif=True)
    else:
        # Manager voit son/ses sites
        sites = [user.userprofile.site] if user.userprofile.site else []
    
    # Statistiques du jour pour les sites du manager
    stats = {}
    for site in sites:
        # Employés du site
        employes_site = UserProfile.objects.filter(
            site=site,
            role='EMPLOYE',
            actif=True
        )
        total_employes = employes_site.count()
        
        # Pointages du jour
        pointages_today = ShiftDay.objects.filter(site=site, date=today)
        presents = pointages_today.filter(clock_in_time__isnull=False).count()
        absents = total_employes - presents
        missed_punch = pointages_today.filter(
            clock_in_time__isnull=False,
            clock_out_time__isnull=True
        ).count()
        
        # Lavages du jour
        lavages_today = CarWash.objects.filter(site=site, date=today)
        total_lavages = lavages_today.count()
        chiffre_jour = lavages_today.aggregate(total=Sum('montant'))['total'] or 0
        
        # Problèmes ouverts
        problemes_ouverts = IssueReport.objects.filter(
            site=site,
            statut__in=['OUVERT', 'EN_COURS']
        ).count()
        
        stats[site.nom] = {
            'total_employes': total_employes,
            'presents': presents,
            'absents': absents,
            'missed_punch': missed_punch,
            'total_lavages': total_lavages,
            'chiffre_jour': chiffre_jour,
            'problemes_ouverts': problemes_ouverts,
            'site_id': site.id,
        }
    
    context = {
        'sites_stats': stats,
        'today': today,
    }
    
    return render(request, 'manager/dashboard.html', context)


@login_required
@user_passes_test(is_manager_or_admin)
def manager_qr_du_jour(request, site_id):
    """
    Afficher et gérer le QR code fixe pour un site
    """
    site = get_object_or_404(Location, id=site_id)
    
    # Vérifier les permissions
    if not request.user.userprofile.is_admin():
        if request.user.userprofile.site != site:
            messages.error(request, "Vous n'avez pas accès à ce site.")
            return redirect('manager_dashboard')
    
    # Générer l'URL du QR fixe
    qr_url = request.build_absolute_uri(site.get_qr_url())
    
    # Générer l'image QR
    qr_image = generate_qr_code_image(qr_url)
    
    context = {
        'site': site,
        'qr_image': qr_image,
        'qr_url': qr_url,
        'site_token': site.site_token,
    }
    
    return render(request, 'manager/qr_du_jour.html', context)


@login_required
@user_passes_test(is_manager_or_admin)
def manager_regenerer_qr(request, site_id):
    """
    Régénérer le site_token (QR fixe) - avec motif obligatoire
    """
    if request.method == 'POST':
        site = get_object_or_404(Location, id=site_id)
        
        # Vérifier les permissions
        if not request.user.userprofile.is_admin():
            if request.user.userprofile.site != site:
                return JsonResponse({
                    'success': False,
                    'message': "Vous n'avez pas accès à ce site."
                })
        
        motif = request.POST.get('motif', '').strip()
        if not motif:
            return JsonResponse({
                'success': False,
                'message': 'Le motif de régénération est obligatoire.'
            })
        
        # Sauvegarder l'ancien token pour l'audit
        ancien_token = str(site.site_token)
        
        # Générer un nouveau site_token
        import uuid
        site.site_token = uuid.uuid4()
        site.save()
        
        # Log d'audit
        AuditLog.log(
            user=request.user,
            action="REGENERER_QR",
            description=f"QR fixe régénéré pour {site.nom}",
            motif=motif,
            content_object=site,
            donnees_avant={'site_token': ancien_token},
            donnees_apres={'site_token': str(site.site_token)},
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )
        
        return JsonResponse({
            'success': True,
            'message': 'QR code régénéré avec succès ! Le nouveau QR doit être imprimé.',
            'redirect_url': f'/manager/qr/{site_id}/'
        })
    
    return JsonResponse({'success': False, 'message': 'Méthode non autorisée'})


@login_required
@user_passes_test(is_manager_or_admin)
def manager_pointages(request):
    """
    Liste des pointages avec filtres
    """
    user = request.user
    
    # Filtres de base
    pointages = ShiftDay.objects.all().order_by('-date', '-clock_in_time')
    
    # Filtrer par site si manager
    if not user.userprofile.is_admin():
        pointages = pointages.filter(site=user.userprofile.site)
    
    # Filtres additionnels via GET
    date_debut = request.GET.get('date_debut')
    date_fin = request.GET.get('date_fin')
    employe_id = request.GET.get('employe')
    site_id = request.GET.get('site')
    
    if date_debut:
        pointages = pointages.filter(date__gte=date_debut)
    if date_fin:
        pointages = pointages.filter(date__lte=date_fin)
    if employe_id:
        pointages = pointages.filter(employe_id=employe_id)
    if site_id and user.userprofile.is_admin():
        pointages = pointages.filter(site_id=site_id)
    
    context = {
        'pointages': pointages[:100],  # Limiter à 100 pour performance
    }
    
    return render(request, 'manager/pointages.html', context)


@login_required
@user_passes_test(is_manager_or_admin)
def manager_corriger_pointage(request, pointage_id):
    """
    Corriger un pointage (avec motif obligatoire)
    """
    pointage = get_object_or_404(ShiftDay, id=pointage_id)
    
    # Vérifier les permissions
    if not request.user.userprofile.is_admin():
        if pointage.site != request.user.userprofile.site:
            messages.error(request, "Vous n'avez pas accès à ce pointage.")
            return redirect('manager_pointages')
    
    if request.method == 'POST':
        try:
            motif = request.POST.get('motif', '').strip()
            if not motif:
                messages.error(request, 'Le motif de correction est obligatoire.')
                return redirect('manager_corriger_pointage', pointage_id=pointage_id)
            
            # Sauvegarder les données avant
            donnees_avant = {
                'clock_in_time': str(pointage.clock_in_time),
                'clock_out_time': str(pointage.clock_out_time) if pointage.clock_out_time else None,
            }
            
            # Appliquer les corrections
            new_clock_in = request.POST.get('clock_in_time')
            new_clock_out = request.POST.get('clock_out_time')
            
            if new_clock_in:
                # Construire datetime complet
                from datetime import datetime
                clock_in_dt = datetime.strptime(
                    f"{pointage.date} {new_clock_in}",
                    "%Y-%m-%d %H:%M"
                )
                pointage.clock_in_time = timezone.make_aware(clock_in_dt)
            
            if new_clock_out:
                from datetime import datetime
                clock_out_dt = datetime.strptime(
                    f"{pointage.date} {new_clock_out}",
                    "%Y-%m-%d %H:%M"
                )
                pointage.clock_out_time = timezone.make_aware(clock_out_dt)
            
            pointage.corrected_by = request.user
            pointage.correction_reason = motif
            pointage.corrected_at = timezone.now()
            pointage.save()
            
            # Données après
            donnees_apres = {
                'clock_in_time': str(pointage.clock_in_time),
                'clock_out_time': str(pointage.clock_out_time) if pointage.clock_out_time else None,
            }
            
            # Log d'audit
            AuditLog.log(
                user=request.user,
                action="CORRIGER_POINTAGE",
                description=f"Pointage corrigé: {pointage}",
                motif=motif,
                content_object=pointage,
                donnees_avant=donnees_avant,
                donnees_apres=donnees_apres,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )
            
            messages.success(request, 'Pointage corrigé avec succès !')
            return redirect('manager_pointages')
            
        except Exception as e:
            messages.error(request, f'Erreur lors de la correction: {str(e)}')
    
    context = {
        'pointage': pointage,
    }
    
    return render(request, 'manager/corriger_pointage.html', context)


@login_required
@user_passes_test(is_manager_or_admin)
def manager_lavages(request):
    """
    Liste des lavages avec totaux (manager uniquement)
    """
    user = request.user
    
    # Filtres de base
    lavages = CarWash.objects.all().order_by('-created_at')
    
    # Filtrer par site si manager
    if not user.userprofile.is_admin():
        lavages = lavages.filter(site=user.userprofile.site)
    
    # Filtres additionnels
    date_debut = request.GET.get('date_debut')
    date_fin = request.GET.get('date_fin')
    employe_id = request.GET.get('employe')
    type_service = request.GET.get('type_service')
    
    if date_debut:
        lavages = lavages.filter(date__gte=date_debut)
    if date_fin:
        lavages = lavages.filter(date__lte=date_fin)
    if employe_id:
        lavages = lavages.filter(employe_id=employe_id)
    if type_service:
        lavages = lavages.filter(type_service=type_service)
    
    # Calculer les totaux
    total_montant = lavages.aggregate(total=Sum('montant'))['total'] or 0
    total_count = lavages.count()
    
    context = {
        'lavages': lavages[:100],  # Limiter à 100
        'total_montant': total_montant,
        'total_count': total_count,
    }
    
    return render(request, 'manager/lavages.html', context)


@login_required
@user_passes_test(is_manager_or_admin)
def manager_problemes(request):
    """
    Liste des problèmes signalés
    """
    user = request.user
    
    # Filtres de base
    problemes = IssueReport.objects.all().order_by('-created_at')
    
    # Filtrer par site si manager
    if not user.userprofile.is_admin():
        problemes = problemes.filter(site=user.userprofile.site)
    
    # Filtres
    statut = request.GET.get('statut')
    categorie = request.GET.get('categorie')
    
    if statut:
        problemes = problemes.filter(statut=statut)
    if categorie:
        problemes = problemes.filter(categorie=categorie)
    
    context = {
        'problemes': problemes[:100],
    }
    
    return render(request, 'manager/problemes.html', context)
