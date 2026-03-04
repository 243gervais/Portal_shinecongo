from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import ShiftDay
from sites.models import Location
from .utils import get_client_ip, get_user_agent
from audit.models import AuditLog
from decimal import Decimal


@login_required
def employe_dashboard(request):
    """
    Dashboard principal pour les employés
    """
    user = request.user
    today = timezone.localdate()

    # Lavages du jour
    lavages_today = user.lavages.filter(date=today).count()
    
    # Problèmes ouverts de l'employé
    problemes_ouverts = user.problemes_signales.filter(statut="OUVERT").count()
    
    context = {
        'lavages_today': lavages_today,
        'problemes_ouverts': problemes_ouverts,
    }
    
    return render(request, 'employe/dashboard.html', context)


@login_required
@require_POST
def scan_qr_clock_in(request):
    """
    Scanner le QR fixe pour pointer l'entrée
    """
    try:
        site_token = request.POST.get('site_token')
        user = request.user
        today = timezone.localdate()
        
        # Vérifier si déjà pointé aujourd'hui
        existing_shift = ShiftDay.objects.filter(employe=user, date=today).first()
        if existing_shift and existing_shift.clock_in_time:
            clock_in_str = existing_shift.clock_in_time.strftime('%H:%M')
            return JsonResponse({
                'success': False,
                'message': f"Vous avez déjà pointé l'entrée aujourd'hui à {clock_in_str}."
            })
        
        # Récupérer le site via site_token
        try:
            site = Location.objects.get(site_token=site_token, actif=True)
        except Location.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'QR code invalide ou non reconnu.'
            })
        
        # Vérifier que le site correspond à l'employé
        employee_site = user.userprofile.site
        if employee_site and employee_site.id != site.id:
            return JsonResponse({
                'success': False,
                'message': 'Ce QR ne correspond pas à votre site.'
            })
        
        # Traiter le GPS optionnel
        gps_lat = request.POST.get('gps_latitude')
        gps_lon = request.POST.get('gps_longitude')
        gps_status = "INCONNU"
        gps_distance = None
        lat = None
        lon = None
        
        if gps_lat and gps_lon:
            try:
                lat = Decimal(str(gps_lat))
                lon = Decimal(str(gps_lon))
                
                if site.gps_actif:
                    distance = site.calculate_distance(lat, lon)
                    if distance is not None:
                        gps_distance = Decimal(str(distance))
                        if distance <= site.rayon_autorisé_mètres:
                            gps_status = "OK"
                        else:
                            gps_status = "HORS_ZONE"
                else:
                    gps_status = "INCONNU"
            except (ValueError, TypeError):
                lat = None
                lon = None
        
        # Créer ou mettre à jour le pointage
        if existing_shift:
            shift = existing_shift
        else:
            shift = ShiftDay.objects.create(
                employe=user,
                site=site,
                date=today
            )
        
        # Enregistrer l'entrée
        shift.clock_in_time = timezone.now()
        if lat is not None and lon is not None:
            shift.clock_in_gps_latitude = lat
            shift.clock_in_gps_longitude = lon
            shift.clock_in_gps_distance_mètres = gps_distance
        shift.clock_in_gps_status = gps_status
        shift.save()
        
        # Messages GPS
        gps_message = ""
        if gps_status == "HORS_ZONE":
            gps_message = " Attention : vous êtes en dehors de la zone du site. Le pointage est enregistré mais signalé."
        elif gps_status == "INCONNU" and site.gps_actif:
            gps_message = " La position GPS n'a pas pu être vérifiée. Le pointage a quand même été enregistré."
        
        # Log d'audit
        AuditLog.log(
            user=user,
            action="AUTRE",
            description=f"Pointage entrée: {shift} (GPS: {gps_status})",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Pointage entrée enregistré avec succès !' + gps_message,
            'time': shift.clock_in_time.strftime('%H:%M'),
            'gps_status': gps_status
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


@login_required
@require_POST
def scan_qr_clock_out(request):
    """
    Scanner le QR fixe pour pointer la sortie et confirmer le rapport
    """
    try:
        site_token = request.POST.get('site_token')
        total_lavages = request.POST.get('total_lavages', 0)
        user = request.user
        today = timezone.localdate()
        
        # Vérifier qu'il y a un pointage d'entrée
        shift = ShiftDay.objects.filter(employe=user, date=today).first()
        if not shift or not shift.clock_in_time:
            return JsonResponse({
                'success': False,
                'message': "Impossible de pointer la sortie sans pointage d'entrée."
            })
        
        # Vérifier si déjà pointé sortie
        if shift.clock_out_time:
            return JsonResponse({
                'success': False,
                'message': f"Vous avez déjà pointé la sortie à {shift.clock_out_time.strftime('%H:%M')}."
            })
        
        # Récupérer le site via site_token
        try:
            site = Location.objects.get(site_token=site_token, actif=True)
        except Location.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'QR code invalide ou non reconnu.'
            })
        
        # Vérifier que le site correspond à l'employé
        employee_site = user.userprofile.site
        if employee_site and employee_site.id != site.id:
            return JsonResponse({
                'success': False,
                'message': 'Ce QR ne correspond pas à votre site.'
            })
        
        # Traiter le GPS optionnel
        gps_lat = request.POST.get('gps_latitude')
        gps_lon = request.POST.get('gps_longitude')
        gps_status = "INCONNU"
        gps_distance = None
        lat = None
        lon = None
        
        if gps_lat and gps_lon:
            try:
                lat = Decimal(str(gps_lat))
                lon = Decimal(str(gps_lon))
                
                if site.gps_actif:
                    distance = site.calculate_distance(lat, lon)
                    if distance is not None:
                        gps_distance = Decimal(str(distance))
                        if distance <= site.rayon_autorisé_mètres:
                            gps_status = "OK"
                        else:
                            gps_status = "HORS_ZONE"
                else:
                    gps_status = "INCONNU"
            except (ValueError, TypeError):
                lat = None
                lon = None
        
        # Mettre à jour le pointage
        shift.clock_out_time = timezone.now()
        if lat is not None and lon is not None:
            shift.clock_out_gps_latitude = lat
            shift.clock_out_gps_longitude = lon
            shift.clock_out_gps_distance_mètres = gps_distance
        shift.clock_out_gps_status = gps_status
        shift.daily_report_confirmed = True
        shift.total_lavages_reported = int(total_lavages)
        shift.save()
        
        # Messages GPS
        gps_message = ""
        if gps_status == "HORS_ZONE":
            gps_message = " Attention : vous êtes en dehors de la zone du site. Le pointage est enregistré mais signalé."
        elif gps_status == "INCONNU" and site.gps_actif:
            gps_message = " La position GPS n'a pas pu être vérifiée. Le pointage a quand même été enregistré."
        
        # Log d'audit
        AuditLog.log(
            user=user,
            action="AUTRE",
            description=f"Pointage sortie: {shift} - {total_lavages} lavages (GPS: {gps_status})",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Pointage sortie enregistré avec succès !' + gps_message,
            'time': shift.clock_out_time.strftime('%H:%M'),
            'gps_status': gps_status
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


@login_required
def scan_qr_fixe(request, site_token):
    """
    Vue publique pour scanner le QR fixe - redirige vers le scan approprié selon l'action
    Cette URL est encodée dans le QR code
    """
    try:
        site = Location.objects.get(site_token=site_token, actif=True)
    except Location.DoesNotExist:
        messages.error(request, 'QR code invalide ou non reconnu.')
        return redirect('employe_dashboard')
    
    # Si l'utilisateur n'est pas connecté, rediriger vers la connexion
    if not request.user.is_authenticated:
        messages.info(request, 'Veuillez vous connecter pour pointer.')
        return redirect('login')
    
    # Vérifier que le site correspond à l'employé
    employee_site = request.user.userprofile.site
    if employee_site and employee_site.id != site.id:
        messages.error(request, 'Ce QR ne correspond pas à votre site.')
        return redirect('employe_dashboard')
    
    # Rediriger vers le dashboard employé (qui gérera le scan)
    return redirect('employe_dashboard')


@login_required
def employe_historique(request):
    """
    Historique des pointages et lavages de l'employé
    """
    user = request.user
    
    # Pointages récents (30 derniers jours)
    pointages = ShiftDay.objects.filter(employe=user).order_by('-date')[:30]
    
    # Lavages récents
    lavages = user.lavages.all().order_by('-created_at')[:50]
    
    # Problèmes signalés
    problemes = user.problemes_signales.all().order_by('-created_at')[:20]
    
    context = {
        'pointages': pointages,
        'lavages': lavages,
        'problemes': problemes,
    }
    
    return render(request, 'employe/historique.html', context)
