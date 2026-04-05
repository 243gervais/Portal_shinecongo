from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Sum
from .models import ShiftDay
from sites.models import Location
from lavages.models import CarWash
from problemes.models import IssueReport
from .utils import get_client_ip, get_user_agent
from audit.models import AuditLog
from decimal import Decimal, InvalidOperation


KNOWN_DAILY_EXPENSES = [
    {
        "key": "transport_personnels",
        "label": "Transport de Personnels",
        "default_amount": Decimal("14000"),
    },
    {
        "key": "achat_savon",
        "label": "Achat Savon",
        "default_amount": Decimal("3000"),
    },
]


def _normalize_fc_amount(value):
    amount = Decimal(str(value or "0")).quantize(Decimal("0.01"))
    if amount < 0:
        raise InvalidOperation
    return amount


def _build_initial_daily_expense_form(shift):
    saved_by_key = {
        item.get("key"): item
        for item in shift.daily_expense_items
        if item.get("is_known") and item.get("key")
    }
    known_items = []
    for expense in KNOWN_DAILY_EXPENSES:
        saved_item = saved_by_key.get(expense["key"])
        amount_value = saved_item["amount_fc"] if saved_item else expense["default_amount"]
        known_items.append({
            "key": expense["key"],
            "label": expense["label"],
            "selected": bool(saved_item),
            "amount_value": f"{Decimal(amount_value):.2f}",
        })

    custom_items = []
    for item in shift.daily_expense_items:
        if item.get("is_known"):
            continue
        custom_items.append({
            "label": item["label"],
            "amount_value": f"{item['amount_fc']:.2f}",
        })

    if not custom_items:
        custom_items.append({"label": "", "amount_value": ""})

    return {
        "known": known_items,
        "custom": custom_items,
        "total": shift.daily_expenses_total_fc or Decimal("0"),
    }


def _parse_daily_expenses_form(post_data):
    expense_items = []
    known_items = []
    custom_items = []
    errors = []

    for expense in KNOWN_DAILY_EXPENSES:
        selected = bool(post_data.get(f"known_expense_{expense['key']}_enabled"))
        amount_value = post_data.get(f"known_expense_{expense['key']}_amount", f"{expense['default_amount']:.2f}").strip()
        known_items.append({
            "key": expense["key"],
            "label": expense["label"],
            "selected": selected,
            "amount_value": amount_value,
        })

        if not selected:
            continue

        try:
            amount_fc = _normalize_fc_amount(amount_value)
        except (ArithmeticError, InvalidOperation, ValueError):
            errors.append(f"Montant invalide pour {expense['label']}.")
            continue

        expense_items.append({
            "key": expense["key"],
            "label": expense["label"],
            "amount_fc": f"{amount_fc:.2f}",
            "is_known": True,
        })

    custom_labels = post_data.getlist("custom_expense_label")
    custom_amounts = post_data.getlist("custom_expense_amount")
    custom_count = max(len(custom_labels), len(custom_amounts))

    for index in range(custom_count):
        label = custom_labels[index].strip() if index < len(custom_labels) else ""
        amount_value = custom_amounts[index].strip() if index < len(custom_amounts) else ""
        custom_items.append({
            "label": label,
            "amount_value": amount_value,
        })

        if not label and not amount_value:
            continue
        if not label:
            errors.append("Chaque dépense supplémentaire doit avoir un nom.")
            continue
        if not amount_value:
            errors.append(f"Montant manquant pour la dépense supplémentaire \"{label}\".")
            continue

        try:
            amount_fc = _normalize_fc_amount(amount_value)
        except (ArithmeticError, InvalidOperation, ValueError):
            errors.append(f"Montant invalide pour la dépense supplémentaire \"{label}\".")
            continue

        expense_items.append({
            "key": "",
            "label": label,
            "amount_fc": f"{amount_fc:.2f}",
            "is_known": False,
        })

    total_expenses = sum((Decimal(item["amount_fc"]) for item in expense_items), Decimal("0"))
    if not custom_items:
        custom_items.append({"label": "", "amount_value": ""})

    return {
        "items": expense_items,
        "known": known_items,
        "custom": custom_items,
        "total": total_expenses,
        "errors": errors,
    }


@login_required
def employe_dashboard(request):
    """
    Dashboard principal pour les employés
    """
    user = request.user
    today = timezone.localdate()

    # Lavages du jour
    lavages_today = user.lavages.filter(date=today).count()
    montant_today = user.lavages.filter(date=today).aggregate(total=Sum('montant'))['total'] or 0
    
    # Problèmes ouverts de l'employé
    problemes_ouverts = user.problemes_signales.filter(statut="OUVERT").count()
    shift_today = ShiftDay.objects.filter(employe=user, date=today).first()
    
    context = {
        'lavages_today': lavages_today,
        'montant_today': montant_today,
        'problemes_ouverts': problemes_ouverts,
        'shift_today': shift_today,
        'show_live_amount': not (shift_today and shift_today.daily_report_confirmed),
    }
    
    return render(request, 'employe/dashboard.html', context)


@login_required
def employe_daily_report(request):
    """
    Rapport de la journée pour l'employé connecté.
    """
    user = request.user
    today = timezone.localdate()

    if not hasattr(user, 'userprofile') or not user.userprofile.site:
        messages.error(request, "Aucun site n'est associé à votre profil.")
        return redirect('employe_dashboard')

    site = user.userprofile.site
    shift, _created = ShiftDay.objects.get_or_create(
        employe=user,
        date=today,
        defaults={'site': site},
    )

    today_washes = CarWash.objects.filter(employe=user, site=site, date=today).order_by('-created_at')
    today_issues = IssueReport.objects.filter(employe=user, site=site, created_at__date=today).order_by('-created_at')

    computed_total_amount = today_washes.aggregate(total=Sum('montant'))['total'] or Decimal('0')
    computed_total_washes = today_washes.count()
    report_submitted = shift.daily_report_confirmed
    expense_form = _build_initial_daily_expense_form(shift)
    submitted_total_amount = (
        f"{shift.total_amount_reported_fc:.2f}"
        if shift.daily_report_confirmed else
        f"{computed_total_amount:.2f}"
    )

    if request.method == 'POST':
        total_amount_value = request.POST.get('total_amount_reported_fc', '').strip()
        submitted_total_amount = total_amount_value
        expense_form = _parse_daily_expenses_form(request.POST)

        try:
            total_amount_reported = Decimal(total_amount_value or '0')
            if total_amount_reported < 0:
                raise ValueError
        except (ArithmeticError, ValueError):
            messages.error(request, "Veuillez entrer une valeur valide pour le montant total.")
            total_amount_reported = None

        if total_amount_reported is None:
            pass
        elif expense_form['errors']:
            for error in expense_form['errors']:
                messages.error(request, error)
        else:
            was_update = shift.daily_report_confirmed
            shift.site = site
            shift.total_amount_reported_fc = total_amount_reported
            shift.total_lavages_reported = computed_total_washes
            shift.lavages_review = ""
            shift.problems_review = ""
            shift.report_notes = ""
            shift.daily_expenses = expense_form['items']
            shift.daily_expenses_total_fc = expense_form['total']
            shift.daily_report_confirmed = True
            shift.save()

            AuditLog.log(
                user=user,
                action="AUTRE",
                description=f"Rapport journalier employé {'mis à jour' if was_update else 'enregistré'}: {site.nom} - {today}",
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            messages.success(
                request,
                "Rapport de la journée mis à jour avec succès."
                if was_update else
                "Rapport de la journée enregistré avec succès."
            )
            return redirect('employe_daily_report')

    context = {
        'shift': shift,
        'today': today,
        'site': site,
        'today_washes': today_washes,
        'today_issues': today_issues,
        'computed_total_amount': computed_total_amount,
        'computed_total_washes': computed_total_washes,
        'report_submitted': report_submitted,
        'expense_form': expense_form,
        'submitted_total_amount': submitted_total_amount,
    }
    return render(request, 'employe/daily_report.html', context)


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
