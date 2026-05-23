import logging
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.db.models import Sum
from .models import ShiftDay
from sites.models import Location, SiteWaterPurchase, get_default_water_supplier
from lavages.models import CarWash
from problemes.models import IssueReport
from .utils import get_client_ip, get_user_agent
from audit.models import AuditLog
from decimal import Decimal, InvalidOperation
from comptes.forms import get_water_purchase_default_amount
from .report_sync import sync_site_finance_from_daily_reports

logger = logging.getLogger(__name__)


KNOWN_DAILY_EXPENSES = [
    {
        "key": "transport_personnels",
        "label": "Transport de Personnels",
        "default_amount": Decimal("14000"),
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


def _format_fc_email_amount(amount):
    return f"{Decimal(amount or 0):,.0f} FC".replace(",", " ")


def _build_final_report_email_context(shift, computed_total_amount, issue_count, was_update):
    employee_name = shift.employe.get_full_name() or shift.employe.username
    action_label = "mis à jour" if was_update else "soumis"
    declared_amount = Decimal(shift.total_amount_reported_fc or 0)
    system_amount = Decimal(computed_total_amount or 0)
    expenses_total = Decimal(shift.daily_expenses_total_fc or 0)
    variance = declared_amount - system_amount
    expense_items = [
        {
            "label": item["label"],
            "amount_display": _format_fc_email_amount(item["amount_fc"]),
        }
        for item in shift.daily_expense_items
    ]

    if variance == 0:
        variance_label = "Aucun écart"
        variance_tone = "match"
    elif variance > 0:
        variance_label = f"Déclaration supérieure de {_format_fc_email_amount(variance)}"
        variance_tone = "high"
    else:
        variance_label = f"Déclaration inférieure de {_format_fc_email_amount(abs(variance))}"
        variance_tone = "low"

    return {
        "company_name": "Shine Congo",
        "employee_name": employee_name,
        "site_name": shift.site.nom,
        "report_date": shift.date,
        "action_label": action_label,
        "action_copy": "Rapport mis à jour" if was_update else "Rapport envoyé",
        "declared_amount_display": _format_fc_email_amount(declared_amount),
        "system_amount_display": _format_fc_email_amount(system_amount),
        "expenses_total_display": _format_fc_email_amount(expenses_total),
        "variance_display": _format_fc_email_amount(abs(variance)),
        "variance_label": variance_label,
        "variance_tone": variance_tone,
        "total_lavages_reported": shift.total_lavages_reported,
        "issue_count": issue_count,
        "expense_items": expense_items,
        "expense_summary": shift.daily_expense_summary,
        "submitted_at": timezone.localtime(shift.updated_at or timezone.now()),
    }


def _send_final_report_notification(shift, computed_total_amount, issue_count, was_update):
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
            "Notification email skipped for final report because SMTP settings are incomplete"
        )
        return False

    context = _build_final_report_email_context(shift, computed_total_amount, issue_count, was_update)
    action_label = context["action_label"]
    subject = (
        f"Rapport de fin de journée {action_label} - "
        f"{shift.site.nom} - {shift.date.strftime('%d/%m/%Y')}"
    )
    message = render_to_string("emails/final_report_notification.txt", context)
    html_message = render_to_string("emails/final_report_notification.html", context)

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
        logger.exception("Impossible d'envoyer la notification email du rapport de fin de journée")
        return False


def _send_water_purchase_notification(purchase):
    recipient = (
        getattr(settings, "WATER_PURCHASE_NOTIFICATION_EMAIL", "")
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
            "Notification email skipped for water purchase because SMTP settings are incomplete"
        )
        return False

    reporter_name = (
        purchase.created_by.get_full_name() or purchase.created_by.username
        if purchase.created_by else
        "Employé non précisé"
    )
    subject = (
        f"Achat d'eau signalé - "
        f"{purchase.site.nom} - {purchase.purchase_date.strftime('%d/%m/%Y')}"
    )
    message = "\n".join([
        f"Employé: {reporter_name}",
        f"Site: {purchase.site.nom}",
        f"Fournisseur: {purchase.supplier.name if purchase.supplier_id else 'Non renseigné'}",
        f"Date d'achat: {purchase.purchase_date.strftime('%d/%m/%Y')}",
        f"Mois rattaché: {purchase.billing_month.strftime('%m/%Y')}",
        f"Montant enregistré: {purchase.amount_fc:,.0f} FC".replace(",", " "),
        "",
        f"Notes: {purchase.notes or 'Aucune note'}",
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
        logger.exception("Impossible d'envoyer la notification email de l'achat d'eau")
        return False


@login_required
@never_cache
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
    shift_today = ShiftDay.objects.filter(employe=user, date=today).first()
    site = getattr(getattr(user, "userprofile", None), "site", None)
    water_purchase_today = None
    water_purchase_month_count = 0
    if site:
        water_purchase_today = (
            SiteWaterPurchase.objects.filter(site=site, purchase_date=today)
            .select_related("created_by")
            .order_by("-created_at")
            .first()
        )
        water_purchase_month_count = SiteWaterPurchase.objects.filter(
            site=site,
            billing_month=today.replace(day=1),
        ).count()
    
    context = {
        'lavages_today': lavages_today,
        'problemes_ouverts': problemes_ouverts,
        'shift_today': shift_today,
        'water_purchase_today': water_purchase_today,
        'water_purchase_month_count': water_purchase_month_count,
    }
    
    return render(request, 'employe/dashboard.html', context)


@login_required
@never_cache
def employe_water_purchase(request):
    """
    Déclaration simple d'un achat d'eau depuis le portail employé.
    Un seul achat par site et par jour est accepté pour éviter les doublons.
    """
    user = request.user
    today = timezone.localdate()
    profile = getattr(user, "userprofile", None)
    site = getattr(profile, "site", None)

    if not site:
        messages.error(request, "Aucun site n'est associé à votre profil.")
        return redirect("employe_dashboard")

    billing_month = today.replace(day=1)
    default_supplier = get_default_water_supplier()
    default_amount = get_water_purchase_default_amount(billing_month, supplier=default_supplier)
    today_purchase = (
        SiteWaterPurchase.objects.filter(site=site, purchase_date=today)
        .select_related("created_by", "supplier")
        .order_by("-created_at")
        .first()
    )

    if request.method == "POST":
        if today_purchase:
            messages.info(
                request,
                "L'achat d'eau du jour a déjà été signalé. L'administrateur peut le corriger si nécessaire.",
            )
            return redirect("employe_water_purchase")

        reporter_name = user.get_full_name() or user.username
        purchase = SiteWaterPurchase.objects.create(
            site=site,
            supplier=default_supplier,
            billing_month=billing_month,
            purchase_date=today,
            amount_fc=default_amount,
            notes=f"Signalé via portail employé par {reporter_name}.",
            created_by=user,
        )
        _send_water_purchase_notification(purchase)

        AuditLog.log(
            user=user,
            action="AUTRE",
            description=(
                f"Achat d'eau signalé via portail employé: "
                f"{site.nom} - {default_supplier.name} - "
                f"{purchase.purchase_date} - {purchase.amount_fc:,.0f} FC"
            ).replace(",", " "),
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        messages.success(
            request,
            "Achat d'eau enregistré pour aujourd'hui.",
        )
        return redirect("employe_water_purchase")

    month_purchases_qs = (
        SiteWaterPurchase.objects.filter(site=site, billing_month=billing_month)
        .select_related("created_by", "supplier")
        .order_by("-purchase_date", "-created_at")
    )
    month_purchase_count = month_purchases_qs.count()
    month_purchases = list(month_purchases_qs[:8])
    last_purchase = month_purchases[0] if month_purchases else None

    context = {
        "site": site,
        "today": today,
        "billing_month": billing_month,
        "default_amount": default_amount,
        "default_supplier": default_supplier,
        "today_purchase": today_purchase,
        "month_purchases": month_purchases,
        "month_purchase_count": month_purchase_count,
        "last_purchase": last_purchase,
    }
    return render(request, "employe/water_purchase.html", context)


@login_required
@never_cache
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
            sync_site_finance_from_daily_reports(site, today, actor=user)
            _send_final_report_notification(
                shift=shift,
                computed_total_amount=computed_total_amount,
                issue_count=today_issues.count(),
                was_update=was_update,
            )

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
@never_cache
def employe_historique(request):
    """
    Historique des pointages et lavages de l'employé
    """
    user = request.user
    today = timezone.localdate()
    profile = getattr(user, "userprofile", None)
    site = getattr(profile, "site", None)
    
    # Pointages récents (30 derniers jours)
    pointages = (
        ShiftDay.objects.filter(employe=user)
        .select_related("site")
        .order_by('-date')[:30]
    )
    report_history = (
        ShiftDay.objects.filter(employe=user)
        .select_related("site")
        .order_by("-date")[:20]
    )
    
    # Lavages récents
    lavages = user.lavages.all().order_by('-created_at')[:50]
    
    # Problèmes signalés
    problemes = user.problemes_signales.all().order_by('-created_at')[:20]

    water_history = []
    water_history_month_count = 0
    if site:
        water_history_qs = (
            SiteWaterPurchase.objects.filter(site=site)
            .select_related("created_by", "supplier")
            .order_by("-purchase_date", "-created_at")
        )
        water_history = list(water_history_qs[:20])
        water_history_month_count = water_history_qs.filter(
            billing_month=today.replace(day=1),
        ).count()

    report_count = ShiftDay.objects.filter(
        employe=user,
        daily_report_confirmed=True,
    ).count()
    pending_report_count = ShiftDay.objects.filter(
        employe=user,
        clock_in_time__isnull=False,
        daily_report_confirmed=False,
    ).count()
    
    context = {
        'site': site,
        'pointages': pointages,
        'report_history': report_history,
        'lavages': lavages,
        'problemes': problemes,
        'water_history': water_history,
        'report_count': report_count,
        'pending_report_count': pending_report_count,
        'water_history_month_count': water_history_month_count,
        'problem_count': user.problemes_signales.count(),
    }
    
    return render(request, 'employe/historique.html', context)
