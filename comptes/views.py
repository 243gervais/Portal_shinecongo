from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout, login
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from functools import wraps
from django.http import HttpResponse
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.contrib.auth.models import User
from datetime import datetime
from decimal import Decimal, InvalidOperation
from .forms import UserRegistrationForm, SiteCreationForm, SiteEmployeeForm, EmployeePaymentForm
from sites.models import Location, DailyBankDeposit, SiteDocument
from lavages.models import CarWash, CarWashPhoto
from problemes.models import IssueReport
from pointage.models import ShiftDay
from comptes.models import UserProfile, EmployeePayment
from audit.models import AuditLog
from pointage.utils import get_client_ip, get_user_agent


def no_cache_view(view_func):
    """
    Décorateur pour ajouter des en-têtes no-cache à une vue
    Empêche la mise en cache des pages protégées
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        response = view_func(request, *args, **kwargs)
        if isinstance(response, HttpResponse):
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            response['X-Content-Type-Options'] = 'nosniff'
        return response
    return _wrapped_view


@login_required
@no_cache_view
def dashboard(request):
    """
    Dashboard principal qui redirige selon le rôle de l'utilisateur
    """
    user = request.user
    
    # Vérifier si l'utilisateur a un profil (sauf pour les superutilisateurs)
    if not user.is_superuser:
        if not hasattr(user, 'userprofile'):
            from django.contrib import messages
            messages.error(request, 'Profil utilisateur non trouvé. Contactez un administrateur.')
            return redirect('admin:index')
        profile = user.userprofile
    else:
        # Pour les superutilisateurs, créer un profil virtuel ou utiliser les valeurs par défaut
        profile = None
    
    # Rediriger selon le rôle
    # Les superutilisateurs Django sont considérés comme admins
    if user.is_superuser or (profile and profile.is_admin()):
        # Pour les admins, rediriger vers le dashboard admin personnalisé
        return redirect('admin_dashboard')
    elif profile and profile.is_manager():
        return redirect('manager_dashboard')
    elif profile and profile.is_employe():
        return redirect('employe_dashboard')
    else:
        # Par défaut pour les superutilisateurs sans profil, rediriger vers admin dashboard
        return redirect('admin_dashboard')


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """
    Vue de déconnexion personnalisée qui redirige vers la page de connexion
    """
    logout(request)
    messages.info(request, 'Vous avez été déconnecté avec succès. Veuillez vous reconnecter pour continuer.')
    
    # Créer une réponse de redirection avec des en-têtes pour empêcher la mise en cache
    response = redirect('login')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


def register_view(request):
    """
    Vue d'inscription pour créer un nouveau compte utilisateur
    """
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(
                request,
                f'Compte créé pour {user.username}. Votre accès est en attente de validation par un administrateur.'
            )
            # Optionnel : connecter automatiquement l'utilisateur après inscription
            # login(request, user)
            # return redirect('dashboard')
            return redirect('login')
    else:
        form = UserRegistrationForm()
    
    return render(request, 'auth/register.html', {
        'form': form
    })


def is_admin_user(user):
    """Vérifier que l'utilisateur est admin"""
    # Les superutilisateurs Django ont automatiquement accès admin
    if user.is_superuser:
        return True
    # Vérifier le profil utilisateur
    if not hasattr(user, 'userprofile'):
        return False
    return user.userprofile.is_admin()


def ensure_superuser_admin_profile(user):
    """
    Ensure Django superusers have an ADMIN profile for custom portal permissions.
    """
    if not user.is_superuser:
        return
    if not hasattr(user, 'userprofile'):
        UserProfile.objects.create(user=user, role='ADMIN')
    elif not user.userprofile.is_admin():
        user.userprofile.role = 'ADMIN'
        user.userprofile.save()


def _safe_next_url(request):
    """
    Retourne l'URL de retour si elle est sûre, sinon None.
    """
    next_url = request.POST.get('next') or request.GET.get('next')
    if not next_url:
        return None
    if url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


def _redirect_to_admin_site_detail(request, site):
    """
    Redirige vers l'URL de retour demandée ou vers le détail du site.
    """
    next_url = _safe_next_url(request)
    if next_url:
        return redirect(next_url)
    return redirect('admin_site_detail', site_id=site.id)


@login_required
@no_cache_view
def admin_dashboard(request):
    """
    Dashboard admin - Liste tous les sites avec leurs statistiques
    """
    user = request.user
    
    # Pour les superutilisateurs, s'assurer qu'ils ont un profil avec le rôle ADMIN
    ensure_superuser_admin_profile(user)
    
    # Vérifier que l'utilisateur est admin
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs. Veuillez vérifier que votre compte a le rôle 'Administrateur' dans votre profil.")
        return redirect('dashboard')
    
    today = timezone.localdate()
    
    # Récupérer tous les sites actifs
    sites = Location.objects.filter(actif=True).order_by('nom')
    
    # Statistiques pour chaque site
    sites_stats = []
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
        
        # Lavages du jour
        lavages_today = CarWash.objects.filter(site=site, date=today)
        total_lavages = lavages_today.count()
        chiffre_jour = lavages_today.aggregate(total=Sum('montant'))['total'] or 0
        
        # Problèmes du jour
        problemes_today = IssueReport.objects.filter(site=site, created_at__date=today)
        problemes_ouverts = IssueReport.objects.filter(
            site=site,
            statut__in=['OUVERT', 'EN_COURS']
        ).count()
        
        sites_stats.append({
            'site': site,
            'total_employes': total_employes,
            'presents': presents,
            'absents': absents,
            'total_lavages': total_lavages,
            'chiffre_jour': chiffre_jour,
            'problemes_today': problemes_today.count(),
            'problemes_ouverts': problemes_ouverts,
        })
    
    pending_users = User.objects.filter(
        is_active=False,
        is_superuser=False
    ).select_related("userprofile", "userprofile__site").order_by("-date_joined")

    pending_account_requests = []
    for pending_user in pending_users:
        profile = getattr(pending_user, "userprofile", None)
        site = profile.site if profile else None
        pending_account_requests.append({
            "id": pending_user.id,
            "username": pending_user.username,
            "email": pending_user.email,
            "telephone": profile.telephone if profile else "",
            "site_name": site.nom if site else "Non assigné",
            "site_address": site.adresse if site and site.adresse else "Adresse non renseignée",
            "requested_at": pending_user.date_joined,
        })

    context = {
        'sites_stats': sites_stats,
        'today': today,
        'pending_account_requests': pending_account_requests,
        'pending_account_requests_count': len(pending_account_requests),
    }
    
    return render(request, 'admin/dashboard.html', context)


@login_required
@require_http_methods(["POST"])
def admin_approve_account_request(request, user_id):
    """
    Approve a pending account request directly from the custom admin dashboard.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette action est réservée aux administrateurs.")
        return redirect('dashboard')

    requested_user = get_object_or_404(User, id=user_id, is_superuser=False)
    requested_user.is_active = True
    requested_user.save(update_fields=["is_active"])

    if hasattr(requested_user, "userprofile"):
        profile = requested_user.userprofile
        profile.actif = True
        profile.save(update_fields=["actif"])

    messages.success(request, f'Compte "{requested_user.username}" approuvé avec succès.')
    return redirect("admin_dashboard")


@login_required
@require_http_methods(["POST"])
def admin_reject_account_request(request, user_id):
    """
    Reject a pending account request directly from the custom admin dashboard.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette action est réservée aux administrateurs.")
        return redirect('dashboard')

    requested_user = get_object_or_404(User, id=user_id, is_superuser=False)
    username = requested_user.username

    if requested_user.is_active:
        messages.warning(request, f'Le compte "{username}" est déjà actif et ne peut pas être rejeté.')
        return redirect("admin_dashboard")

    requested_user.delete()
    messages.success(request, f'Demande de compte "{username}" rejetée et supprimée.')
    return redirect("admin_dashboard")


@login_required
@no_cache_view
def admin_site_detail(request, site_id):
    """
    Vue détaillée d'un site pour l'admin - Affiche l'argent, problèmes, photos, etc.
    Supporte le filtrage par date pour voir l'historique complet.
    """
    user = request.user
    
    # Pour les superutilisateurs, s'assurer qu'ils ont un profil avec le rôle ADMIN
    ensure_superuser_admin_profile(user)
    
    # Vérifier que l'utilisateur est admin
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')
    
    site = get_object_or_404(Location, id=site_id)
    today = timezone.localdate()
    
    # Récupérer les paramètres de filtre de date
    date_debut = request.GET.get('date_debut')
    date_fin = request.GET.get('date_fin')
    filter_today = request.GET.get('filter_today', 'false') == 'true'
    selected_single_date = None  # Date unique sélectionnée pour affichage détaillé
    
    # Par défaut, afficher tous les lavages (pas seulement aujourd'hui)
    # Sauf si l'utilisateur demande explicitement de filtrer sur aujourd'hui
    if filter_today:
        # Filtrer uniquement sur aujourd'hui
        lavages_query = CarWash.objects.filter(site=site, date=today)
        selected_date_start = today
        selected_date_end = today
        selected_single_date = today
    elif date_debut and date_fin and date_debut == date_fin:
        # Une seule date sélectionnée - affichage détaillé
        try:
            selected_single_date = datetime.strptime(date_debut, '%Y-%m-%d').date()
            lavages_query = CarWash.objects.filter(site=site, date=selected_single_date)
            selected_date_start = selected_single_date
            selected_date_end = selected_single_date
        except ValueError:
            lavages_query = CarWash.objects.filter(site=site)
            selected_date_start = None
            selected_date_end = None
    elif date_debut or date_fin:
        # Filtrer sur une plage de dates
        lavages_query = CarWash.objects.filter(site=site)
        if date_debut:
            lavages_query = lavages_query.filter(date__gte=date_debut)
            selected_date_start = date_debut
        else:
            selected_date_start = None
        if date_fin:
            lavages_query = lavages_query.filter(date__lte=date_fin)
            selected_date_end = date_fin
        else:
            selected_date_end = None
    else:
        # Afficher tous les lavages (pas de filtre)
        lavages_query = CarWash.objects.filter(site=site)
        selected_date_start = None
        selected_date_end = None
    
    # Récupérer les lavages avec photos, triés par date décroissante
    lavages_all = lavages_query.prefetch_related('photos').order_by('-date', '-created_at')
    total_lavages = lavages_all.count()
    chiffre_periode = lavages_all.aggregate(total=Sum('montant'))['total'] or 0
    
    # Toutes les photos des lavages filtrés
    photos_lavages = []
    for lavage in lavages_all:
        for photo in lavage.photos.all():
            photos_lavages.append({
                'photo': photo,
                'lavage': lavage,
                'employe': lavage.employe,
                'montant': lavage.montant,
                'type_service': lavage.get_type_service_display(),
                'created_at': lavage.created_at,
                'date': lavage.date,
            })
    
    # Déterminer la date pour les détails quotidiens (aujourd'hui ou date sélectionnée)
    detail_date = selected_single_date if selected_single_date else today
    
    # Problèmes du jour sélectionné
    problemes_date = IssueReport.objects.filter(site=site, created_at__date=detail_date).order_by('-created_at')
    
    # Problèmes ouverts (tous statuts, toutes dates)
    problemes_ouverts = IssueReport.objects.filter(
        site=site,
        statut__in=['OUVERT', 'EN_COURS']
    ).order_by('-created_at')
    
    # Pointages de la date sélectionnée avec calcul de durée
    pointages_date = ShiftDay.objects.filter(site=site, date=detail_date).select_related('employe').order_by('-clock_in_time')
    presents = pointages_date.filter(clock_in_time__isnull=False).count()
    
    # Ajouter la durée formatée pour chaque pointage
    pointages_with_duration = []
    for pointage in pointages_date:
        duration_str = None
        if pointage.clock_in_time and pointage.clock_out_time:
            duration = pointage.clock_out_time - pointage.clock_in_time
            total_seconds = int(duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            duration_str = f"{hours}h{minutes:02d}min"
        
        pointages_with_duration.append({
            'pointage': pointage,
            'duration': duration_str
        })
    
    # Statistiques par employé pour la date sélectionnée
    lavages_by_employee = {}
    if selected_single_date:
        lavages_date = CarWash.objects.filter(site=site, date=selected_single_date).select_related('employe')
        for lavage in lavages_date:
            emp_id = lavage.employe.id
            if emp_id not in lavages_by_employee:
                lavages_by_employee[emp_id] = {
                    'employe': lavage.employe,
                    'count': 0,
                    'total': 0,
                    'average': 0,
                    'lavages': []
                }
            lavages_by_employee[emp_id]['count'] += 1
            lavages_by_employee[emp_id]['total'] += float(lavage.montant)
            lavages_by_employee[emp_id]['lavages'].append(lavage)
        
        # Calculer les moyennes
        for emp_data in lavages_by_employee.values():
            if emp_data['count'] > 0:
                emp_data['average'] = emp_data['total'] / emp_data['count']
    
    # Employés du site
    employes_site = UserProfile.objects.filter(
        site=site,
        role='EMPLOYE',
        actif=True
    ).select_related('user')
    
    # Déterminer le label de période pour l'affichage
    if filter_today:
        period_label = "Aujourd'hui"
    elif selected_single_date:
        period_label = selected_single_date.strftime("%d/%m/%Y")
    elif date_debut and date_fin:
        period_label = f"Du {date_debut} au {date_fin}"
    elif date_debut:
        period_label = f"Depuis le {date_debut}"
    elif date_fin:
        period_label = f"Jusqu'au {date_fin}"
    else:
        period_label = "Tous les lavages"
    
    # Récupérer le dépôt bancaire pour la date sélectionnée
    bank_deposit_date = DailyBankDeposit.objects.filter(site=site, date=detail_date).first()
    bank_deposit_amount_date = bank_deposit_date.amount if bank_deposit_date else 0
    
    # Calculer le cash flow pour la date sélectionnée
    chiffre_date = CarWash.objects.filter(site=site, date=detail_date).aggregate(total=Sum('montant'))['total'] or 0
    difference_date = chiffre_date - bank_deposit_amount_date
    
    # Cash flow d'aujourd'hui (pour comparaison)
    chiffre_jour = CarWash.objects.filter(site=site, date=today).aggregate(total=Sum('montant'))['total'] or 0
    bank_deposit_today = DailyBankDeposit.objects.filter(site=site, date=today).first()
    bank_deposit_amount_today = bank_deposit_today.amount if bank_deposit_today else 0
    difference_today = chiffre_jour - bank_deposit_amount_today
    
    context = {
        'site': site,
        'today': today,
        'detail_date': detail_date,
        'selected_single_date': selected_single_date,
        'lavages_all': lavages_all,
        'total_lavages': total_lavages,
        'chiffre_periode': chiffre_periode,
        'chiffre_date': chiffre_date,
        'chiffre_jour': chiffre_jour,
        'bank_deposit_date': bank_deposit_date,
        'bank_deposit_amount_date': bank_deposit_amount_date,
        'bank_deposit_today': bank_deposit_today,
        'bank_deposit_amount_today': bank_deposit_amount_today,
        'difference_date': difference_date,
        'difference_today': difference_today,
        'photos_lavages': photos_lavages,
        'problemes_date': problemes_date,
        'problemes_ouverts': problemes_ouverts,
        'pointages_date': pointages_with_duration,
        'presents': presents,
        'employes_site': employes_site,
        'lavages_by_employee': lavages_by_employee,
        'date_debut': date_debut,
        'date_fin': date_fin,
        'filter_today': filter_today,
        'period_label': period_label,
    }
    
    # Ajouter les statistiques des documents
    documents_count = SiteDocument.objects.filter(site=site).count()
    context['documents_count'] = documents_count
    
    return render(request, 'admin/site_detail.html', context)


@login_required
@no_cache_view
def admin_create_site(request):
    """
    Create a new site from the custom admin dashboard.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    if request.method == 'POST':
        form = SiteCreationForm(request.POST)
        if form.is_valid():
            site = form.save()
            messages.success(request, f'Site "{site.nom}" créé avec succès.')
            return redirect('admin_site_detail', site_id=site.id)
    else:
        form = SiteCreationForm(initial={"ville": "Kinshasa", "actif": True, "rayon_autorisé_mètres": 50})

    return render(request, 'admin/create_site.html', {"form": form})


@login_required
@no_cache_view
def admin_add_daily_total(request, site_id):
    """
    Vue pour permettre à l'admin d'ajouter simplement le montant total d'une date
    sans créer un lavage complet avec photos
    """
    user = request.user
    
    # Pour les superutilisateurs, s'assurer qu'ils ont un profil avec le rôle ADMIN
    if user.is_superuser:
        if not hasattr(user, 'userprofile'):
            UserProfile.objects.create(user=user, role='ADMIN')
        elif not user.userprofile.is_admin():
            user.userprofile.role = 'ADMIN'
            user.userprofile.save()
    
    # Vérifier que l'utilisateur est admin
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')
    
    site = get_object_or_404(Location, id=site_id)
    
    if request.method == 'POST':
        try:
            # Récupérer les données du formulaire
            date_total = request.POST.get('date')
            montant_total = request.POST.get('montant_total')
            notes = request.POST.get('notes', '')
            
            # Validation des champs requis
            if not date_total:
                messages.error(request, 'La date est requise.')
                return render(request, 'admin/add_daily_total.html', {
                    'site': site,
                })
            
            if not montant_total:
                messages.error(request, 'Le montant total est requis.')
                return render(request, 'admin/add_daily_total.html', {
                    'site': site,
                })
            
            # Convertir la date
            try:
                date_obj = datetime.strptime(date_total, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'Format de date invalide.')
                return render(request, 'admin/add_daily_total.html', {
                    'site': site,
                })
            
            # Vérifier le montant
            try:
                montant_decimal = float(montant_total)
                if montant_decimal < 0:
                    messages.error(request, 'Le montant ne peut pas être négatif.')
                    return render(request, 'admin/add_daily_total.html', {
                        'site': site,
                    })
            except ValueError:
                messages.error(request, 'Montant invalide.')
                return render(request, 'admin/add_daily_total.html', {
                    'site': site,
                })
            
            # Créer un lavage "résumé" avec l'admin comme employé
            # Ce lavage représente le total de la journée sans détails spécifiques
            lavage = CarWash.objects.create(
                employe=user,  # L'admin qui ajoute le total
                site=site,
                date=date_obj,
                type_service='COMPLET',  # Type par défaut
                plaque='',  # Pas de plaque pour un total
                montant=montant_decimal,
                notes=f"Total quotidien ajouté manuellement par l'admin. {notes}".strip()
            )
            
            # Log d'audit
            AuditLog.log(
                user=user,
                action="CREER",
                description=f"Montant total quotidien ajouté manuellement: {montant_decimal} FC pour le {date_obj.strftime('%d/%m/%Y')}",
                content_object=lavage,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )
            
            messages.success(request, f'Montant total de {montant_decimal:,.0f} FC ajouté avec succès pour le {date_obj.strftime("%d/%m/%Y")} !')
            return redirect('admin_site_detail', site_id=site.id)
            
        except Exception as e:
            messages.error(request, f'Erreur lors de l\'enregistrement: {str(e)}')
    
    # GET request - afficher le formulaire
    today = timezone.localdate()
    
    # Calculer le total actuel pour aujourd'hui (si existe)
    total_actuel = CarWash.objects.filter(site=site, date=today).aggregate(total=Sum('montant'))['total'] or 0
    
    return render(request, 'admin/add_daily_total.html', {
        'site': site,
        'today': today,
        'total_actuel': total_actuel,
    })


@login_required
@no_cache_view
def admin_add_wash(request, site_id):
    """
    Vue pour permettre à l'admin d'ajouter manuellement un lavage pour une date spécifique
    """
    user = request.user
    
    # Pour les superutilisateurs, s'assurer qu'ils ont un profil avec le rôle ADMIN
    if user.is_superuser:
        if not hasattr(user, 'userprofile'):
            UserProfile.objects.create(user=user, role='ADMIN')
        elif not user.userprofile.is_admin():
            user.userprofile.role = 'ADMIN'
            user.userprofile.save()
    
    # Vérifier que l'utilisateur est admin
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')
    
    site = get_object_or_404(Location, id=site_id)
    
    # Récupérer les employés du site
    employes_site = UserProfile.objects.filter(
        site=site,
        role='EMPLOYE',
        actif=True
    ).select_related('user')
    
    if request.method == 'POST':
        try:
            # Récupérer les données du formulaire
            employe_id = request.POST.get('employe')
            date_wash = request.POST.get('date')
            type_service = request.POST.get('type_service')
            plaque = request.POST.get('plaque', '')
            montant = request.POST.get('montant')
            notes = request.POST.get('notes', '')
            
            # Validation des champs requis
            if not employe_id:
                messages.error(request, 'L\'employé est requis.')
                return render(request, 'admin/add_wash.html', {
                    'site': site,
                    'employes_site': employes_site,
                    'types_service': CarWash.TYPE_SERVICE_CHOICES,
                })
            
            if not date_wash:
                messages.error(request, 'La date est requise.')
                return render(request, 'admin/add_wash.html', {
                    'site': site,
                    'employes_site': employes_site,
                    'types_service': CarWash.TYPE_SERVICE_CHOICES,
                })
            
            if not type_service:
                messages.error(request, 'Le type de service est requis.')
                return render(request, 'admin/add_wash.html', {
                    'site': site,
                    'employes_site': employes_site,
                    'types_service': CarWash.TYPE_SERVICE_CHOICES,
                })
            
            if not montant:
                messages.error(request, 'Le montant est requis.')
                return render(request, 'admin/add_wash.html', {
                    'site': site,
                    'employes_site': employes_site,
                    'types_service': CarWash.TYPE_SERVICE_CHOICES,
                })
            
            # Vérifier qu'il y a au moins une photo
            photos = request.FILES.getlist('photos')
            if not photos:
                messages.error(request, 'Au moins une photo est requise.')
                return render(request, 'admin/add_wash.html', {
                    'site': site,
                    'employes_site': employes_site,
                    'types_service': CarWash.TYPE_SERVICE_CHOICES,
                })
            
            # Récupérer l'employé
            employe = get_object_or_404(User, id=employe_id)
            
            # Vérifier que l'employé appartient au site
            if not hasattr(employe, 'userprofile') or employe.userprofile.site != site:
                messages.error(request, 'L\'employé sélectionné n\'appartient pas à ce site.')
                return render(request, 'admin/add_wash.html', {
                    'site': site,
                    'employes_site': employes_site,
                    'types_service': CarWash.TYPE_SERVICE_CHOICES,
                })
            
            # Convertir la date
            try:
                date_obj = datetime.strptime(date_wash, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'Format de date invalide.')
                return render(request, 'admin/add_wash.html', {
                    'site': site,
                    'employes_site': employes_site,
                    'types_service': CarWash.TYPE_SERVICE_CHOICES,
                })
            
            # Créer le lavage
            lavage = CarWash.objects.create(
                employe=employe,
                site=site,
                date=date_obj,
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
                    type_photo='APRES'
                )
            
            # Log d'audit
            AuditLog.log(
                user=user,
                action="CREER",
                description=f"Lavage ajouté manuellement par admin: {lavage} (Date: {date_obj})",
                content_object=lavage,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )
            
            messages.success(request, f'Lavage enregistré avec succès pour le {date_obj.strftime("%d/%m/%Y")} !')
            return redirect('admin_site_detail', site_id=site.id)
            
        except Exception as e:
            messages.error(request, f'Erreur lors de l\'enregistrement: {str(e)}')
    
    # GET request - afficher le formulaire
    today = timezone.localdate()
    return render(request, 'admin/add_wash.html', {
        'site': site,
        'employes_site': employes_site,
        'types_service': CarWash.TYPE_SERVICE_CHOICES,
        'today': today,
    })


@login_required
@no_cache_view
def admin_edit_wash(request, site_id, lavage_id):
    """
    Modifier un lavage existant (lavage saisi par employé ou admin).
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    lavage = get_object_or_404(
        CarWash.objects.select_related('employe', 'site'),
        id=lavage_id,
        site=site,
    )
    employes_site = UserProfile.objects.filter(
        site=site,
        role='EMPLOYE',
        actif=True
    ).select_related('user')

    if request.method == 'POST':
        try:
            motif = request.POST.get('motif', '').strip()
            if not motif:
                messages.error(request, "Le motif de modification est obligatoire.")
                return redirect('admin_edit_wash', site_id=site.id, lavage_id=lavage.id)

            employe_id = request.POST.get('employe')
            date_wash = request.POST.get('date')
            type_service = request.POST.get('type_service')
            plaque = request.POST.get('plaque', '').strip()
            montant = request.POST.get('montant')
            notes = request.POST.get('notes', '').strip()
            photos = request.FILES.getlist('photos')

            if not employe_id or not date_wash or not type_service or not montant:
                messages.error(request, "Employé, date, type de service et montant sont requis.")
                return redirect('admin_edit_wash', site_id=site.id, lavage_id=lavage.id)

            valid_service_types = {choice[0] for choice in CarWash.TYPE_SERVICE_CHOICES}
            if type_service not in valid_service_types:
                messages.error(request, "Type de service invalide.")
                return redirect('admin_edit_wash', site_id=site.id, lavage_id=lavage.id)

            employe = get_object_or_404(User, id=employe_id)
            if not hasattr(employe, 'userprofile') or employe.userprofile.site != site:
                messages.error(request, "L'employé sélectionné n'appartient pas à ce site.")
                return redirect('admin_edit_wash', site_id=site.id, lavage_id=lavage.id)

            try:
                date_obj = datetime.strptime(date_wash, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, "Format de date invalide.")
                return redirect('admin_edit_wash', site_id=site.id, lavage_id=lavage.id)

            try:
                montant_decimal = Decimal(montant)
                if montant_decimal < 0:
                    raise InvalidOperation
            except (InvalidOperation, TypeError):
                messages.error(request, "Montant invalide.")
                return redirect('admin_edit_wash', site_id=site.id, lavage_id=lavage.id)

            donnees_avant = {
                'employe': lavage.employe.username,
                'date': str(lavage.date),
                'type_service': lavage.type_service,
                'plaque': lavage.plaque,
                'montant': str(lavage.montant),
                'notes': lavage.notes,
            }

            lavage.employe = employe
            lavage.date = date_obj
            lavage.type_service = type_service
            lavage.plaque = plaque
            lavage.montant = montant_decimal
            lavage.notes = notes
            lavage.save()

            added_photos = 0
            for photo in photos:
                CarWashPhoto.objects.create(
                    lavage=lavage,
                    photo=photo,
                    type_photo='APRES',
                )
                added_photos += 1

            donnees_apres = {
                'employe': lavage.employe.username,
                'date': str(lavage.date),
                'type_service': lavage.type_service,
                'plaque': lavage.plaque,
                'montant': str(lavage.montant),
                'notes': lavage.notes,
                'photos_ajoutees': added_photos,
            }

            AuditLog.log(
                user=user,
                action="MODIFIER",
                description=f"Lavage modifié par admin: {lavage}",
                motif=motif,
                content_object=lavage,
                donnees_avant=donnees_avant,
                donnees_apres=donnees_apres,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            if added_photos:
                messages.success(request, f"Lavage modifié avec succès. {added_photos} photo(s) ajoutée(s).")
            else:
                messages.success(request, "Lavage modifié avec succès.")
            return _redirect_to_admin_site_detail(request, site)
        except Exception as e:
            messages.error(request, f"Erreur lors de la modification du lavage: {str(e)}")

    return render(request, 'admin/edit_wash.html', {
        'site': site,
        'lavage': lavage,
        'employes_site': employes_site,
        'types_service': CarWash.TYPE_SERVICE_CHOICES,
        'next_url': _safe_next_url(request) or '',
    })


@login_required
@no_cache_view
def admin_delete_wash(request, site_id, lavage_id):
    """
    Supprimer un lavage existant.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    lavage = get_object_or_404(
        CarWash.objects.select_related('employe', 'site'),
        id=lavage_id,
        site=site,
    )

    if request.method == 'POST':
        motif = request.POST.get('motif', '').strip()
        if not motif:
            messages.error(request, "Le motif de suppression est obligatoire.")
            return redirect('admin_delete_wash', site_id=site.id, lavage_id=lavage.id)

        donnees_avant = {
            'id': lavage.id,
            'employe': lavage.employe.username,
            'date': str(lavage.date),
            'type_service': lavage.type_service,
            'plaque': lavage.plaque,
            'montant': str(lavage.montant),
            'photos': lavage.photos.count(),
        }
        lavage_label = str(lavage)
        lavage.delete()

        AuditLog.log(
            user=user,
            action="SUPPRIMER",
            description=f"Lavage supprimé par admin: {lavage_label}",
            motif=motif,
            donnees_avant=donnees_avant,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        messages.success(request, "Lavage supprimé avec succès.")
        return _redirect_to_admin_site_detail(request, site)

    return render(request, 'admin/delete_wash.html', {
        'site': site,
        'lavage': lavage,
        'next_url': _safe_next_url(request) or '',
    })


@login_required
@no_cache_view
def admin_edit_pointage(request, site_id, pointage_id):
    """
    Corriger un pointage depuis le portail admin.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    pointage = get_object_or_404(
        ShiftDay.objects.select_related('employe', 'site', 'corrected_by'),
        id=pointage_id,
        site=site,
    )

    if request.method == 'POST':
        try:
            motif = request.POST.get('motif', '').strip()
            if not motif:
                messages.error(request, "Le motif de correction est obligatoire.")
                return redirect('admin_edit_pointage', site_id=site.id, pointage_id=pointage.id)

            donnees_avant = {
                'clock_in_time': str(pointage.clock_in_time) if pointage.clock_in_time else None,
                'clock_out_time': str(pointage.clock_out_time) if pointage.clock_out_time else None,
                'daily_report_confirmed': pointage.daily_report_confirmed,
                'total_lavages_reported': pointage.total_lavages_reported,
            }

            new_clock_in = request.POST.get('clock_in_time', '').strip()
            new_clock_out = request.POST.get('clock_out_time', '').strip()
            clear_clock_out = request.POST.get('clear_clock_out') == 'on'
            total_lavages_reported = request.POST.get('total_lavages_reported', '').strip()
            pointage.daily_report_confirmed = request.POST.get('daily_report_confirmed') == 'on'

            if new_clock_in:
                clock_in_dt = datetime.strptime(
                    f"{pointage.date} {new_clock_in}",
                    "%Y-%m-%d %H:%M"
                )
                pointage.clock_in_time = timezone.make_aware(clock_in_dt)

            if new_clock_out:
                clock_out_dt = datetime.strptime(
                    f"{pointage.date} {new_clock_out}",
                    "%Y-%m-%d %H:%M"
                )
                pointage.clock_out_time = timezone.make_aware(clock_out_dt)
            elif clear_clock_out:
                pointage.clock_out_time = None

            if total_lavages_reported:
                total_lavages_int = int(total_lavages_reported)
                if total_lavages_int < 0:
                    raise ValueError("Le total des lavages ne peut pas être négatif.")
                pointage.total_lavages_reported = total_lavages_int

            if pointage.clock_in_time and pointage.clock_out_time and pointage.clock_out_time < pointage.clock_in_time:
                messages.error(request, "L'heure de sortie ne peut pas être avant l'heure d'entrée.")
                return redirect('admin_edit_pointage', site_id=site.id, pointage_id=pointage.id)

            pointage.corrected_by = user
            pointage.correction_reason = motif
            pointage.corrected_at = timezone.now()
            pointage.save()

            donnees_apres = {
                'clock_in_time': str(pointage.clock_in_time) if pointage.clock_in_time else None,
                'clock_out_time': str(pointage.clock_out_time) if pointage.clock_out_time else None,
                'daily_report_confirmed': pointage.daily_report_confirmed,
                'total_lavages_reported': pointage.total_lavages_reported,
            }

            AuditLog.log(
                user=user,
                action="CORRIGER_POINTAGE",
                description=f"Pointage corrigé par admin: {pointage}",
                motif=motif,
                content_object=pointage,
                donnees_avant=donnees_avant,
                donnees_apres=donnees_apres,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            messages.success(request, "Pointage corrigé avec succès.")
            return _redirect_to_admin_site_detail(request, site)
        except ValueError as e:
            messages.error(request, f"Erreur de validation: {str(e)}")
        except Exception as e:
            messages.error(request, f"Erreur lors de la correction du pointage: {str(e)}")

    return render(request, 'admin/edit_pointage.html', {
        'site': site,
        'pointage': pointage,
        'next_url': _safe_next_url(request) or '',
    })


@login_required
@no_cache_view
def admin_delete_pointage(request, site_id, pointage_id):
    """
    Supprimer un pointage existant.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    pointage = get_object_or_404(
        ShiftDay.objects.select_related('employe', 'site'),
        id=pointage_id,
        site=site,
    )

    if request.method == 'POST':
        motif = request.POST.get('motif', '').strip()
        if not motif:
            messages.error(request, "Le motif de suppression est obligatoire.")
            return redirect('admin_delete_pointage', site_id=site.id, pointage_id=pointage.id)

        donnees_avant = {
            'id': pointage.id,
            'employe': pointage.employe.username,
            'date': str(pointage.date),
            'clock_in_time': str(pointage.clock_in_time) if pointage.clock_in_time else None,
            'clock_out_time': str(pointage.clock_out_time) if pointage.clock_out_time else None,
            'total_lavages_reported': pointage.total_lavages_reported,
        }
        pointage_label = str(pointage)
        pointage.delete()

        AuditLog.log(
            user=user,
            action="SUPPRIMER",
            description=f"Pointage supprimé par admin: {pointage_label}",
            motif=motif,
            donnees_avant=donnees_avant,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        messages.success(request, "Pointage supprimé avec succès.")
        return _redirect_to_admin_site_detail(request, site)

    return render(request, 'admin/delete_pointage.html', {
        'site': site,
        'pointage': pointage,
        'next_url': _safe_next_url(request) or '',
    })


@login_required
@no_cache_view
def admin_add_bank_deposit(request, site_id):
    """
    Vue pour permettre à l'admin d'ajouter ou modifier le dépôt bancaire quotidien
    """
    user = request.user
    
    # Pour les superutilisateurs, s'assurer qu'ils ont un profil avec le rôle ADMIN
    if user.is_superuser:
        if not hasattr(user, 'userprofile'):
            UserProfile.objects.create(user=user, role='ADMIN')
        elif not user.userprofile.is_admin():
            user.userprofile.role = 'ADMIN'
            user.userprofile.save()
    
    # Vérifier que l'utilisateur est admin
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')
    
    site = get_object_or_404(Location, id=site_id)
    
    if request.method == 'POST':
        try:
            # Récupérer les données du formulaire
            date_deposit = request.POST.get('date')
            amount = request.POST.get('amount')
            notes = request.POST.get('notes', '')
            
            # Validation des champs requis
            if not date_deposit:
                messages.error(request, 'La date est requise.')
                return render(request, 'admin/add_bank_deposit.html', {
                    'site': site,
                    'deposit': None,
                })
            
            if not amount:
                messages.error(request, 'Le montant est requis.')
                return render(request, 'admin/add_bank_deposit.html', {
                    'site': site,
                    'deposit': None,
                })
            
            # Convertir la date
            try:
                date_obj = datetime.strptime(date_deposit, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'Format de date invalide.')
                return render(request, 'admin/add_bank_deposit.html', {
                    'site': site,
                    'deposit': None,
                })
            
            # Vérifier le montant
            try:
                amount_decimal = float(amount)
                if amount_decimal < 0:
                    messages.error(request, 'Le montant ne peut pas être négatif.')
                    return render(request, 'admin/add_bank_deposit.html', {
                        'site': site,
                        'deposit': None,
                    })
            except ValueError:
                messages.error(request, 'Montant invalide.')
                return render(request, 'admin/add_bank_deposit.html', {
                    'site': site,
                    'deposit': None,
                })
            
            # Créer ou mettre à jour le dépôt bancaire
            deposit, created = DailyBankDeposit.objects.update_or_create(
                site=site,
                date=date_obj,
                defaults={
                    'amount': amount_decimal,
                    'notes': notes,
                    'created_by': user,
                }
            )
            
            # Log d'audit
            action = "CREER" if created else "MODIFIER"
            AuditLog.log(
                user=user,
                action=action,
                description=f"Dépôt bancaire {'créé' if created else 'modifié'}: {amount_decimal} FC pour le {date_obj.strftime('%d/%m/%Y')}",
                content_object=deposit,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )
            
            messages.success(request, f'Dépôt bancaire de {amount_decimal:,.0f} FC {"ajouté" if created else "modifié"} avec succès pour le {date_obj.strftime("%d/%m/%Y")} !')
            return redirect('admin_site_detail', site_id=site.id)
            
        except Exception as e:
            messages.error(request, f'Erreur lors de l\'enregistrement: {str(e)}')
    
    # GET request - afficher le formulaire
    today = timezone.localdate()
    
    # Récupérer le dépôt existant pour aujourd'hui (si existe)
    deposit = DailyBankDeposit.objects.filter(site=site, date=today).first()
    
    # Si une date est passée en paramètre GET, utiliser cette date
    date_param = request.GET.get('date')
    if date_param:
        try:
            date_obj = datetime.strptime(date_param, '%Y-%m-%d').date()
            deposit = DailyBankDeposit.objects.filter(site=site, date=date_obj).first()
            today = date_obj
        except ValueError:
            pass
    
    return render(request, 'admin/add_bank_deposit.html', {
        'site': site,
        'today': today,
        'deposit': deposit,
    })


@login_required
@no_cache_view
def admin_site_documents(request, site_id):
    """
    Vue pour gérer les documents et les employés d'un site.
    """
    user = request.user
    
    # Pour les superutilisateurs, s'assurer qu'ils ont un profil avec le rôle ADMIN
    if user.is_superuser:
        if not hasattr(user, 'userprofile'):
            UserProfile.objects.create(user=user, role='ADMIN')
        elif not user.userprofile.is_admin():
            user.userprofile.role = 'ADMIN'
            user.userprofile.save()
    
    # Vérifier que l'utilisateur est admin
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')
    
    site = get_object_or_404(Location, id=site_id)
    
    # Documents du site
    all_documents = SiteDocument.objects.filter(site=site).select_related('uploaded_by').order_by('-uploaded_at')
    documents_total_count = all_documents.count()
    documents_by_type = {}
    for doc in all_documents:
        file_type = doc.file_type
        if file_type not in documents_by_type:
            documents_by_type[file_type] = []
        documents_by_type[file_type].append(doc)
    
    filter_type = request.GET.get('type')
    if filter_type:
        all_documents = all_documents.filter(file_type=filter_type)

    # Employés du site (actifs + inactifs pour gestion complète)
    site_employees = UserProfile.objects.filter(
        site=site,
        role='EMPLOYE'
    ).select_related('user').order_by('-actif', 'user__first_name', 'user__last_name', 'user__username')

    # Historique des paiements
    selected_employee = request.GET.get('employee')
    payment_records = EmployeePayment.objects.filter(site=site).select_related(
        'employee_profile',
        'employee_profile__user',
        'created_by',
    )
    if selected_employee:
        payment_records = payment_records.filter(employee_profile_id=selected_employee)
    payment_records = payment_records.order_by('-payment_date', '-created_at')
    
    context = {
        'site': site,
        'all_documents': all_documents,
        'documents_by_type': documents_by_type,
        'file_types': SiteDocument.FILE_TYPE_CHOICES,
        'filter_type': filter_type,
        'documents_total_count': documents_total_count,
        'site_employees': site_employees,
        'payment_records': payment_records,
        'selected_employee': str(selected_employee) if selected_employee else '',
    }
    
    return render(request, 'admin/site_documents.html', context)


@login_required
@no_cache_view
def admin_add_site_employee(request, site_id):
    """
    Ajouter un employé pour un site.
    """
    user = request.user
    ensure_superuser_admin_profile(user)
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)

    if request.method == 'POST':
        form = SiteEmployeeForm(request.POST)
        if form.is_valid():
            profile = form.save(site=site)
            employee_name = profile.user.get_full_name() or profile.user.username
            AuditLog.log(
                user=user,
                action="CREER",
                description=f"Employé ajouté sur {site.nom}: {employee_name}",
                content_object=profile,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )
            messages.success(request, f'Employé "{employee_name}" ajouté avec succès.')
            return redirect('admin_site_documents', site_id=site.id)
    else:
        form = SiteEmployeeForm()

    return render(request, 'admin/site_employee_form.html', {
        'site': site,
        'form': form,
        'mode': 'create',
    })


@login_required
@no_cache_view
def admin_edit_site_employee(request, site_id, profile_id):
    """
    Modifier les informations d'un employé rattaché à un site.
    """
    user = request.user
    ensure_superuser_admin_profile(user)
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    profile = get_object_or_404(
        UserProfile.objects.select_related('user'),
        id=profile_id,
        site=site,
        role='EMPLOYE',
    )

    if request.method == 'POST':
        form = SiteEmployeeForm(
            request.POST,
            user_instance=profile.user,
            profile_instance=profile,
        )
        if form.is_valid():
            updated_profile = form.save(site=site)
            employee_name = updated_profile.user.get_full_name() or updated_profile.user.username
            AuditLog.log(
                user=user,
                action="MODIFIER",
                description=f"Employé modifié sur {site.nom}: {employee_name}",
                content_object=updated_profile,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )
            messages.success(request, f'Informations de "{employee_name}" mises à jour.')
            return redirect('admin_site_documents', site_id=site.id)
    else:
        form = SiteEmployeeForm(user_instance=profile.user, profile_instance=profile)

    return render(request, 'admin/site_employee_form.html', {
        'site': site,
        'employee_profile': profile,
        'form': form,
        'mode': 'edit',
    })


@login_required
@no_cache_view
def admin_remove_site_employee(request, site_id, profile_id):
    """
    Retirer un employé d'un site (désactivation du compte).
    """
    user = request.user
    ensure_superuser_admin_profile(user)
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    profile = get_object_or_404(
        UserProfile.objects.select_related('user'),
        id=profile_id,
        site=site,
        role='EMPLOYE',
    )
    employee_name = profile.user.get_full_name() or profile.user.username

    if request.method == 'POST':
        profile.site = None
        profile.actif = False
        profile.save(update_fields=['site', 'actif', 'updated_at'])

        profile.user.is_active = False
        profile.user.save(update_fields=['is_active'])

        AuditLog.log(
            user=user,
            action="MODIFIER",
            description=f"Employé retiré du site {site.nom}: {employee_name}",
            content_object=profile,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        messages.success(request, f'"{employee_name}" a été retiré du site et désactivé.')
        return redirect('admin_site_documents', site_id=site.id)

    return render(request, 'admin/site_employee_delete.html', {
        'site': site,
        'employee_profile': profile,
    })


@login_required
@no_cache_view
def admin_create_employee_payment(request, site_id, profile_id):
    """
    Enregistrer un paiement employé puis générer une fiche de paiement.
    """
    user = request.user
    ensure_superuser_admin_profile(user)
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    employee_profile = get_object_or_404(
        UserProfile.objects.select_related('user'),
        id=profile_id,
        site=site,
        role='EMPLOYE',
    )

    if request.method == 'POST':
        form = EmployeePaymentForm(request.POST, employee_profile=employee_profile)
        if form.is_valid():
            salary_base = employee_profile.salaire_mensuel_usd
            if salary_base is None:
                salary_base = form.cleaned_data['amount_paid_usd']

            admin_signature = user.get_full_name() or user.username

            payment = EmployeePayment.objects.create(
                employee_profile=employee_profile,
                site=site,
                payment_date=form.cleaned_data['payment_date'],
                period_start=form.cleaned_data['period_start'],
                period_end=form.cleaned_data['period_end'],
                salary_base_usd=salary_base,
                amount_paid_usd=form.cleaned_data['amount_paid_usd'],
                payment_method=form.cleaned_data['payment_method'],
                mpesa_reference=form.cleaned_data['mpesa_reference'],
                employee_signature_name=form.cleaned_data['employee_signature_name'],
                admin_signature_name=admin_signature,
                notes=form.cleaned_data['notes'],
                created_by=user,
            )

            AuditLog.log(
                user=user,
                action="CREER",
                description=(
                    f"Paiement employé créé sur {site.nom}: "
                    f"{employee_profile.user.get_full_name() or employee_profile.user.username} "
                    f"({payment.amount_paid_usd} USD)"
                ),
                content_object=payment,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            messages.success(request, "Paiement enregistré. La fiche de paiement a été générée.")
            return redirect('admin_employee_payment_receipt', site_id=site.id, payment_id=payment.id)
    else:
        form = EmployeePaymentForm(employee_profile=employee_profile)

    return render(request, 'admin/payment_record_form.html', {
        'site': site,
        'employee_profile': employee_profile,
        'form': form,
    })


@login_required
@no_cache_view
def admin_employee_payment_receipt(request, site_id, payment_id):
    """
    Afficher la fiche de paiement (version imprimable).
    """
    user = request.user
    ensure_superuser_admin_profile(user)
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    payment = get_object_or_404(
        EmployeePayment.objects.select_related('employee_profile', 'employee_profile__user', 'created_by'),
        id=payment_id,
        site=site,
    )

    context = {
        'site': site,
        'payment': payment,
        'company_name': "Shine Congo",
    }
    return render(request, 'admin/payment_receipt.html', context)


@login_required
@no_cache_view
def admin_upload_site_document(request, site_id):
    """
    Vue pour uploader un nouveau document pour un site
    """
    user = request.user
    
    # Pour les superutilisateurs, s'assurer qu'ils ont un profil avec le rôle ADMIN
    if user.is_superuser:
        if not hasattr(user, 'userprofile'):
            UserProfile.objects.create(user=user, role='ADMIN')
        elif not user.userprofile.is_admin():
            user.userprofile.role = 'ADMIN'
            user.userprofile.save()
    
    # Vérifier que l'utilisateur est admin
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')
    
    site = get_object_or_404(Location, id=site_id)
    
    if request.method == 'POST':
        try:
            file_type = request.POST.get('file_type')
            title = request.POST.get('title')
            description = request.POST.get('description', '')
            files = request.FILES.getlist('file')
            
            # Validation
            if not file_type:
                messages.error(request, 'Le type de fichier est requis.')
                return render(request, 'admin/upload_site_document.html', {
                    'site': site,
                    'file_types': SiteDocument.FILE_TYPE_CHOICES,
                })
            
            if not title:
                messages.error(request, 'Le titre est requis.')
                return render(request, 'admin/upload_site_document.html', {
                    'site': site,
                    'file_types': SiteDocument.FILE_TYPE_CHOICES,
                })
            
            if not files:
                messages.error(request, 'Au moins un fichier est requis.')
                return render(request, 'admin/upload_site_document.html', {
                    'site': site,
                    'file_types': SiteDocument.FILE_TYPE_CHOICES,
                })

            created_documents = []
            total_files = len(files)
            for index, uploaded_file in enumerate(files, start=1):
                generated_title = title
                if total_files > 1:
                    generated_title = f"{title} ({index})"

                document = SiteDocument.objects.create(
                    site=site,
                    file_type=file_type,
                    title=generated_title,
                    description=description,
                    file=uploaded_file,
                    uploaded_by=user
                )
                created_documents.append(document)

                # Log d'audit
                AuditLog.log(
                    user=user,
                    action="CREER",
                    description=f"Document uploadé pour le site {site.nom}: {generated_title} ({document.get_file_type_display()})",
                    content_object=document,
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request)
                )

            if total_files == 1:
                messages.success(request, f'Document "{created_documents[0].title}" uploadé avec succès !')
            else:
                messages.success(request, f'{total_files} fichiers uploadés avec succès.')
            return redirect('admin_site_documents', site_id=site.id)
            
        except Exception as e:
            messages.error(request, f'Erreur lors de l\'upload: {str(e)}')
    
    return render(request, 'admin/upload_site_document.html', {
        'site': site,
        'file_types': SiteDocument.FILE_TYPE_CHOICES,
    })


@login_required
@no_cache_view
def admin_delete_site_document(request, site_id, document_id):
    """
    Vue pour supprimer un document d'un site
    """
    user = request.user
    
    # Vérifier que l'utilisateur est admin
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')
    
    site = get_object_or_404(Location, id=site_id)
    document = get_object_or_404(SiteDocument, id=document_id, site=site)
    
    if request.method == 'POST':
        title = document.title
        document.delete()
        
        # Log d'audit
        AuditLog.log(
            user=user,
            action="SUPPRIMER",
            description=f"Document supprimé pour le site {site.nom}: {title}",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )
        
        messages.success(request, f'Document "{title}" supprimé avec succès.')
        return redirect('admin_site_documents', site_id=site.id)
    
    return render(request, 'admin/delete_site_document.html', {
        'site': site,
        'document': document,
    })
