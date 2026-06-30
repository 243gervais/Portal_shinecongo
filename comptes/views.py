import calendar
from io import BytesIO
from urllib.parse import quote
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout, login, update_session_auth_hash
from django.contrib.staticfiles import finders
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from functools import wraps
from django.http import HttpResponse, Http404, FileResponse
from django.contrib import messages
from django.db.models import Sum, Count, Q, Min, Max, Prefetch
from django.contrib.auth.models import User
from django.core import signing
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from xhtml2pdf import pisa
from comptes.pagination import paginate_queryset
from .forms import (
    AdminReminderForm,
    CameraForm,
    DailyCameraReportForm,
    AdminPasswordReferenceForm,
    UserRegistrationForm,
    SiteCreationForm,
    SiteEmployeeForm,
    AdminPasswordManagementForm,
    EmployeePaymentForm,
    SiteJournalEntryForm,
    SiteJournalEntryMoveForm,
    SiteDocumentMoveForm,
    SiteWaterPurchaseForm,
    SiteWaterPurchaseMoveForm,
    WaterSupplierForm,
    VideoEvidenceForm,
    get_water_purchase_default_amount,
)
from sites.models import (
    Camera,
    CameraObservation,
    DailyCameraReport,
    CameraOperatorDailyReport,
    Location,
    DailyBankDeposit,
    SiteDocument,
    SiteFuelPurchase,
    SiteLossEntry,
    SiteJournalEntry,
    SiteWaterPurchase,
    VideoEvidence,
    WaterSupplier,
    get_default_water_supplier,
)
from lavages.models import CarWash, CarWashPhoto
from pointage.attendance import get_clock_in_status, get_clock_out_status
from problemes.models import IssueReport
from pointage.models import ShiftDay
from pointage.views import _build_initial_daily_expense_form, _parse_daily_expenses_form
from pointage.report_sync import ADMIN_CORRECTION_SOURCE, sync_site_finance_from_daily_reports
from comptes.models import AdminReminder, UserProfile, EmployeePayment
from audit.models import AuditLog
from pointage.utils import get_client_ip, get_user_agent
from comptes.admin_inbox import mark_admin_inbox_seen, mark_admin_messages_seen


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


MONTH_NAMES = [
    "Janvier",
    "Fevrier",
    "Mars",
    "Avril",
    "Mai",
    "Juin",
    "Juillet",
    "Aout",
    "Septembre",
    "Octobre",
    "Novembre",
    "Decembre",
]


def _to_decimal_amount(value):
    try:
        return Decimal(str(value or 0))
    except (ArithmeticError, TypeError, ValueError):
        return Decimal("0")


def _build_admin_reminders_snapshot(reference_date=None):
    today = reference_date or timezone.localdate()
    now = timezone.now()
    priority_rank = {"URGENT": 0, "IMPORTANT": 1, "INFO": 2}

    active_manual_reminders = list(
        AdminReminder.objects.filter(is_resolved=False)
        .select_related("created_by")
        .order_by("due_at", "-created_at")
    )
    far_future = now + timedelta(days=3650)
    active_manual_reminders.sort(
        key=lambda reminder: (
            reminder.due_at is None,
            reminder.due_at or far_future,
            priority_rank.get(reminder.priority, 3),
            -(reminder.created_at.timestamp() if reminder.created_at else 0),
        )
    )

    upcoming_birthdays = []
    employee_profiles = (
        UserProfile.objects.filter(
            role="EMPLOYE",
            actif=True,
            user__is_active=True,
            site__actif=True,
            date_naissance__isnull=False,
        )
        .select_related("site", "user")
        .order_by("site__nom", "user__first_name", "user__last_name", "user__username")
    )
    for profile in employee_profiles:
        next_birthday = profile.prochaine_date_anniversaire(today)
        if not next_birthday:
            continue
        days_until = max((next_birthday - today).days, 0)
        if days_until > 30:
            continue
        employee_name = profile.user.get_full_name() or profile.user.username
        if days_until == 0:
            countdown_label = "Aujourd'hui"
        elif days_until == 1:
            countdown_label = "Demain"
        else:
            countdown_label = f"Dans {days_until} jours"
        upcoming_birthdays.append(
            {
                "profile": profile,
                "employee_name": employee_name,
                "site_name": profile.site.nom if profile.site else "Site non assigné",
                "next_birthday": next_birthday,
                "days_until": days_until,
                "countdown_label": countdown_label,
                "turning_age": next_birthday.year - profile.date_naissance.year,
                "portal_url": reverse(
                    "admin_site_employee_portal",
                    kwargs={"site_id": profile.site.id, "profile_id": profile.id},
                ) if profile.site else "",
            }
        )

    upcoming_birthdays.sort(
        key=lambda item: (
            item["days_until"],
            item["site_name"],
            item["employee_name"].lower(),
        )
    )

    overdue_manual_count = sum(
        1
        for reminder in active_manual_reminders
        if reminder.due_at and timezone.localtime(reminder.due_at).date() < today
    )
    due_this_week_count = sum(
        1
        for reminder in active_manual_reminders
        if reminder.due_at and 0 <= (timezone.localtime(reminder.due_at).date() - today).days <= 7
    )

    return {
        "manual_reminders": active_manual_reminders,
        "upcoming_birthdays": upcoming_birthdays,
        "summary": {
            "manual_count": len(active_manual_reminders),
            "birthday_count": len(upcoming_birthdays),
            "website_count": sum(1 for reminder in active_manual_reminders if reminder.target == "WEBSITE"),
            "portal_count": sum(1 for reminder in active_manual_reminders if reminder.target == "PORTAL"),
            "overdue_count": overdue_manual_count,
            "due_this_week_count": due_this_week_count,
            "total_visible": len(active_manual_reminders) + len(upcoming_birthdays),
        },
    }


def _build_site_comparison_periods(site, detail_date, selected_scope="week"):
    week_start = detail_date - timedelta(days=detail_date.weekday())

    earliest_activity_candidates = [
        CarWash.objects.filter(site=site).aggregate(value=Min("date"))["value"],
        DailyBankDeposit.objects.filter(site=site).aggregate(value=Min("date"))["value"],
        SiteLossEntry.objects.filter(site=site).aggregate(value=Min("date"))["value"],
        ShiftDay.objects.filter(site=site, daily_report_confirmed=True).aggregate(value=Min("date"))["value"],
    ]
    earliest_activity_date = min(
        (date_value for date_value in earliest_activity_candidates if date_value),
        default=week_start,
    )

    def build_period_history(period_key, current_start, history_limit):
        entries = []
        cursor = current_start

        while len(entries) < history_limit:
            if period_key == "week":
                period_end = cursor + timedelta(days=6)
                label = f"{cursor.strftime('%d/%m/%Y')} - {period_end.strftime('%d/%m/%Y')}"
                detail_query = (
                    f"date_debut={cursor.strftime('%Y-%m-%d')}"
                    f"&date_fin={period_end.strftime('%Y-%m-%d')}"
                    f"&week_anchor={cursor.strftime('%Y-%m-%d')}"
                )
                previous_cursor = cursor - timedelta(days=7)
            elif period_key == "month":
                period_end = cursor.replace(day=calendar.monthrange(cursor.year, cursor.month)[1])
                label = f"{MONTH_NAMES[cursor.month - 1]} {cursor.year}"
                detail_query = (
                    f"date_debut={cursor.strftime('%Y-%m-%d')}"
                    f"&date_fin={period_end.strftime('%Y-%m-%d')}"
                )
                previous_cursor = (cursor - timedelta(days=1)).replace(day=1)
            else:
                period_end = cursor.replace(month=12, day=31)
                label = str(cursor.year)
                detail_query = (
                    f"date_debut={cursor.strftime('%Y-%m-%d')}"
                    f"&date_fin={period_end.strftime('%Y-%m-%d')}"
                )
                previous_cursor = cursor.replace(year=cursor.year - 1, month=1, day=1)

            if period_end < earliest_activity_date:
                break

            history_cash = CarWash.objects.filter(
                site=site,
                date__gte=cursor,
                date__lte=period_end,
            ).aggregate(total=Sum("montant"))["total"] or 0
            history_bank = DailyBankDeposit.objects.filter(
                site=site,
                date__gte=cursor,
                date__lte=period_end,
            ).aggregate(total=Sum("amount"))["total"] or 0
            history_losses = SiteLossEntry.objects.filter(
                site=site,
                date__gte=cursor,
                date__lte=period_end,
            )
            history_pertes_total = history_losses.aggregate(total=Sum("amount"))["total"] or 0
            history_pertes_caisse = history_losses.filter(funding_source="CAISSE").aggregate(total=Sum("amount"))["total"] or 0
            history_pertes_banque = history_losses.filter(funding_source="BANQUE").aggregate(total=Sum("amount"))["total"] or 0

            if history_cash or history_bank or history_pertes_total or cursor == current_start:
                history_reports = ShiftDay.objects.filter(
                    site=site,
                    date__gte=cursor,
                    date__lte=period_end,
                    daily_report_confirmed=True,
                )
                history_report_total = history_reports.aggregate(total=Sum("total_amount_reported_fc"))["total"] or 0
                ecart_caisse = history_cash - history_bank - history_pertes_caisse
                bank_net = history_bank - history_pertes_banque
                entries.append(
                    {
                        "period_start": cursor,
                        "period_end": period_end,
                        "label": label,
                        "cash_flow": history_cash,
                        "reported_cash": history_report_total,
                        "bank_deposit": history_bank,
                        "bank_net": bank_net,
                        "pertes_total": history_pertes_total,
                        "pertes_caisse": history_pertes_caisse,
                        "pertes_banque": history_pertes_banque,
                        "ecart_caisse": ecart_caisse,
                        "abs_ecart_caisse": abs(ecart_caisse),
                        "detail_query": detail_query,
                        "is_selected": cursor == current_start,
                    }
                )

            cursor = previous_cursor

        for index, item in enumerate(entries):
            previous_item = entries[index + 1] if index + 1 < len(entries) else None
            item["cash_flow_delta"] = item["cash_flow"] - previous_item["cash_flow"] if previous_item else None
            item["reported_cash_delta"] = item["reported_cash"] - previous_item["reported_cash"] if previous_item else None
            item["bank_deposit_delta"] = item["bank_deposit"] - previous_item["bank_deposit"] if previous_item else None
            item["bank_net_delta"] = item["bank_net"] - previous_item["bank_net"] if previous_item else None
            item["pertes_total_delta"] = item["pertes_total"] - previous_item["pertes_total"] if previous_item else None
            item["ecart_caisse_delta"] = item["ecart_caisse"] - previous_item["ecart_caisse"] if previous_item else None

        return entries

    weekly_history = build_period_history("week", week_start, 8)
    monthly_history = build_period_history("month", detail_date.replace(day=1), 6)
    yearly_history = build_period_history("year", detail_date.replace(month=1, day=1), 5)

    def build_monthly_week_cash_rankings(month_items):
        month_rankings = []
        for month_item in month_items:
            month_start = month_item["period_start"]
            month_end = month_item["period_end"]
            ranked_weeks = []
            cursor = month_start

            while cursor <= month_end:
                week_end = min(cursor + timedelta(days=(6 - cursor.weekday())), month_end)
                week_cash_flow = CarWash.objects.filter(
                    site=site,
                    date__gte=cursor,
                    date__lte=week_end,
                ).aggregate(total=Sum("montant"))["total"] or 0

                ranked_weeks.append(
                    {
                        "period_start": cursor,
                        "period_end": week_end,
                        "label": f"{cursor.strftime('%d/%m')} - {week_end.strftime('%d/%m')}",
                        "cash_flow": week_cash_flow,
                    }
                )
                cursor = week_end + timedelta(days=1)

            ranked_weeks.sort(
                key=lambda item: (
                    -item["cash_flow"],
                    item["period_start"],
                )
            )

            for rank_index, week_item in enumerate(ranked_weeks, start=1):
                week_item["rank"] = rank_index
                week_item["is_best"] = rank_index == 1

            month_rankings.append(
                {
                    "month_label": month_item["label"],
                    "month_cash_flow": month_item["cash_flow"],
                    "week_count": len(ranked_weeks),
                    "best_week": ranked_weeks[0] if ranked_weeks else None,
                    "weeks": ranked_weeks,
                }
            )

        return month_rankings

    monthly_week_cash_rankings = build_monthly_week_cash_rankings(monthly_history)

    period_definitions = [
        {
            "key": "week",
            "toggle_label": "Hebdomadaire",
            "title": "Historique hebdomadaire",
            "copy": "Comparer les 8 dernieres semaines actives et rouvrir rapidement une semaine precise.",
            "row_label": "Semaine",
            "items": weekly_history,
            "empty_message": "Aucune semaine historique disponible pour ce site.",
            "show_correction_link": True,
        },
        {
            "key": "month",
            "toggle_label": "Mensuel",
            "title": "Historique mensuel",
            "copy": "Comparer les derniers mois actifs pour repérer rapidement les variations de rythme et de charges.",
            "row_label": "Mois",
            "items": monthly_history,
            "weekly_cash_rankings": monthly_week_cash_rankings,
            "empty_message": "Aucun mois historique disponible pour ce site.",
            "show_correction_link": False,
        },
        {
            "key": "year",
            "toggle_label": "Annuel",
            "title": "Historique annuel",
            "copy": "Voir la trajectoire annuelle du site sans empiler toutes les semaines sur un seul ecran.",
            "row_label": "Annee",
            "items": yearly_history,
            "weekly_cash_rankings": [],
            "empty_message": "Aucune annee historique disponible pour ce site.",
            "show_correction_link": False,
        },
    ]

    comparison_periods = []
    for definition in period_definitions:
        items = definition["items"]
        best_cash_item = max(items, key=lambda item: item["cash_flow"], default=None)
        highest_loss_item = max(items, key=lambda item: item["pertes_total"], default=None)
        strongest_bank_item = max(items, key=lambda item: item["bank_net"], default=None)
        closest_gap_item = min(items, key=lambda item: abs(item["ecart_caisse"]), default=None)
        current_item = items[0] if items else None
        previous_item = items[1] if len(items) > 1 else None

        comparison_periods.append(
            {
                **definition,
                "item_count": len(items),
                "max_cash_flow": max((item["cash_flow"] for item in items), default=0) or 1,
                "max_bank_deposit": max((item["bank_deposit"] for item in items), default=0) or 1,
                "max_pertes_total": max((item["pertes_total"] for item in items), default=0) or 1,
                "max_ecart_caisse": max((item["abs_ecart_caisse"] for item in items), default=0) or 1,
                "default_open": definition["key"] == selected_scope,
                "current_item": current_item,
                "previous_item": previous_item,
                "best_cash_item": best_cash_item,
                "highest_loss_item": highest_loss_item,
                "strongest_bank_item": strongest_bank_item,
                "closest_gap_item": closest_gap_item,
            }
        )

    return comparison_periods


def _build_next_month_forecast(detail_date, comparison_periods):
    monthly_period = next((period for period in comparison_periods if period["key"] == "month"), None)
    monthly_items = monthly_period["items"] if monthly_period else []
    current_month_item = monthly_items[0] if monthly_items else None

    current_month_days = calendar.monthrange(detail_date.year, detail_date.month)[1]
    elapsed_days = max(1, min(detail_date.day, current_month_days))
    current_month_factor = Decimal(str(current_month_days)) / Decimal(str(elapsed_days))

    month_cursor = detail_date.replace(day=1)
    if month_cursor.month == 12:
        next_month_start = month_cursor.replace(year=month_cursor.year + 1, month=1)
    else:
        next_month_start = month_cursor.replace(month=month_cursor.month + 1)
    next_month_end = next_month_start.replace(day=calendar.monthrange(next_month_start.year, next_month_start.month)[1])

    metric_keys = [
        "cash_flow",
        "reported_cash",
        "bank_deposit",
        "bank_net",
        "pertes_total",
        "ecart_caisse",
    ]

    projected_current_month = {}
    if current_month_item:
        for metric in metric_keys:
            projected_current_month[metric] = (_to_decimal_amount(current_month_item[metric]) * current_month_factor).quantize(
                Decimal("0.01")
            )

    baseline_items = []
    if projected_current_month:
        baseline_items.append(projected_current_month)
    for item in monthly_items[1:4]:
        baseline_items.append({metric: _to_decimal_amount(item[metric]) for metric in metric_keys})

    forecast_metrics = {metric: Decimal("0") for metric in metric_keys}
    if baseline_items:
        for metric in metric_keys:
            values = [_to_decimal_amount(item.get(metric)) for item in baseline_items]
            forecast_metrics[metric] = (sum(values, Decimal("0")) / Decimal(str(len(values)))).quantize(Decimal("0.01"))

    prior_full_month = monthly_items[1] if len(monthly_items) > 1 else None
    current_projected_cash = projected_current_month.get("cash_flow", Decimal("0"))
    prior_cash = _to_decimal_amount(prior_full_month["cash_flow"]) if prior_full_month else Decimal("0")
    forecast_cash = forecast_metrics["cash_flow"]
    forecast_loss = forecast_metrics["pertes_total"]
    forecast_bank_net = forecast_metrics["bank_net"]

    def percent_change(current_value, previous_value):
        current_decimal = _to_decimal_amount(current_value)
        previous_decimal = _to_decimal_amount(previous_value)
        if previous_decimal == 0:
            return None
        return ((current_decimal - previous_decimal) / previous_decimal * Decimal("100")).quantize(Decimal("0.1"))

    projected_loss_rate = Decimal("0")
    if forecast_cash > 0:
        projected_loss_rate = ((forecast_loss / forecast_cash) * Decimal("100")).quantize(Decimal("0.1"))

    projected_bank_capture = Decimal("0")
    if forecast_cash > 0:
        projected_bank_capture = ((forecast_bank_net / forecast_cash) * Decimal("100")).quantize(Decimal("0.1"))

    return {
        "label": f"{MONTH_NAMES[next_month_start.month - 1]} {next_month_start.year}",
        "period_start": next_month_start,
        "period_end": next_month_end,
        "metrics": forecast_metrics,
        "current_month_label": current_month_item["label"] if current_month_item else "",
        "previous_month_label": prior_full_month["label"] if prior_full_month else "",
        "baseline_count": len(baseline_items),
        "baseline_labels": [
            current_month_item["label"] + " (rythme projeté)" if index == 0 and current_month_item else item["label"]
            for index, item in enumerate(([current_month_item] if current_month_item else []) + monthly_items[1:4])
            if item
        ],
        "current_month_projected": projected_current_month,
        "forecast_vs_current_projection_pct": percent_change(forecast_cash, current_projected_cash),
        "forecast_vs_previous_month_pct": percent_change(forecast_cash, prior_cash),
        "loss_rate_pct": projected_loss_rate,
        "bank_capture_pct": projected_bank_capture,
        "assumption": (
            "Estimation basée sur le rythme du mois en cours et les trois derniers mois disponibles."
            if baseline_items
            else "Aucune base historique suffisante pour établir une estimation fiable."
        ),
    }


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
    elif profile and profile.is_camera_controller():
        return redirect('camera_dashboard')
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


def _redirect_to_admin_site_detail(request, site, date_obj=None):
    """
    Redirige vers l'URL de retour demandée ou vers le détail du site.
    """
    next_url = _safe_next_url(request)
    if next_url:
        return redirect(next_url)
    if date_obj:
        date_query = date_obj.strftime('%Y-%m-%d')
        base_url = reverse('admin_site_detail', kwargs={'site_id': site.id})
        return redirect(f"{base_url}?date_debut={date_query}&date_fin={date_query}")
    return redirect('admin_site_detail', site_id=site.id)


def _redirect_to_site_losses(request, site, date_obj=None):
    """
    Redirige vers l'URL de retour demandée ou vers la gestion des pertes du site.
    """
    next_url = _safe_next_url(request)
    if next_url:
        return redirect(next_url)
    base_url = reverse('admin_site_losses', kwargs={'site_id': site.id})
    if date_obj:
        return redirect(f"{base_url}?date={date_obj.strftime('%Y-%m-%d')}")
    return redirect(base_url)


def _format_fc_compact(amount):
    """
    Formate un montant FC sans décimales pour les libellés courts de formulaires.
    """
    return f"{amount:,.0f}".replace(",", " ")


def _normalize_month_start(value=None):
    """
    Retourne le premier jour du mois pour la date fournie ou pour aujourd'hui.
    """
    if value is None:
        value = timezone.localdate()
    return value.replace(day=1)


def _parse_month_filter(raw_value):
    """
    Parse un champ HTML month (YYYY-MM) et retourne le premier jour du mois.
    """
    if not raw_value:
        return _normalize_month_start()
    try:
        parsed = datetime.strptime(raw_value, "%Y-%m").date()
    except ValueError:
        return _normalize_month_start()
    return parsed.replace(day=1)


def _previous_month_start(month_start):
    """
    Retourne le premier jour du mois précédent.
    """
    return (month_start - timedelta(days=1)).replace(day=1)


def _next_month_start(month_start):
    """
    Retourne le premier jour du mois suivant.
    """
    if month_start.month == 12:
        return month_start.replace(year=month_start.year + 1, month=1, day=1)
    return month_start.replace(month=month_start.month + 1, day=1)


def _month_label(month_start):
    """
    Libellé mois/année cohérent pour les vues historiques.
    """
    return f"{MONTH_NAMES[month_start.month - 1]} {month_start.year}"


def _date_is_in_month(value, month_start):
    return bool(
        value
        and month_start
        and value.year == month_start.year
        and value.month == month_start.month
    )


def _water_week_bounds_for_month(month_start, target_date):
    month_last_day = date(
        month_start.year,
        month_start.month,
        calendar.monthrange(month_start.year, month_start.month)[1],
    )
    week_cursor = month_start
    while week_cursor <= month_last_day:
        week_end = min(week_cursor + timedelta(days=(6 - week_cursor.weekday())), month_last_day)
        if week_cursor <= target_date <= week_end:
            return week_cursor, week_end
        week_cursor = week_end + timedelta(days=1)
    return None, None


def _summarize_daily_reports(queryset):
    """
    Agrégation standard des rapports de fin de journée.
    """
    summary = queryset.aggregate(
        report_count=Count("id"),
        days_count=Count("date", distinct=True),
        sites_count=Count("site", distinct=True),
        employees_count=Count("employe", distinct=True),
        amount_total=Sum("total_amount_reported_fc"),
        expenses_total=Sum("daily_expenses_total_fc"),
    )
    amount_total = _to_decimal_amount(summary["amount_total"])
    expenses_total = _to_decimal_amount(summary["expenses_total"])
    report_count = summary["report_count"] or 0

    average_amount = Decimal("0")
    if report_count:
        average_amount = (amount_total / Decimal(str(report_count))).quantize(Decimal("0.01"))

    return {
        "report_count": report_count,
        "days_count": summary["days_count"] or 0,
        "sites_count": summary["sites_count"] or 0,
        "employees_count": summary["employees_count"] or 0,
        "amount_total": amount_total,
        "expenses_total": expenses_total,
        "net_total": amount_total - expenses_total,
        "average_amount": average_amount,
    }


def _build_admin_daily_report_history(selected_month, selected_site=None):
    """
    Construit la vue historique des rapports de fin de journée pour l'admin.
    """
    today = timezone.localdate()
    month_start = _normalize_month_start(selected_month)
    month_end = month_start.replace(day=calendar.monthrange(month_start.year, month_start.month)[1])
    year_start = today.replace(month=1, day=1)

    reports_qs = ShiftDay.objects.filter(
        daily_report_confirmed=True,
        site__actif=True,
    ).select_related("employe", "site", "employe__userprofile")

    if selected_site:
        reports_qs = reports_qs.filter(site=selected_site)

    reports_qs = reports_qs.order_by("-date", "-updated_at", "-id")
    month_reports_qs = reports_qs.filter(date__gte=month_start, date__lte=month_end)
    today_reports_qs = reports_qs.filter(date=today)
    year_reports_qs = reports_qs.filter(date__gte=year_start, date__lte=today)

    all_time_summary = _summarize_daily_reports(reports_qs)
    today_summary = _summarize_daily_reports(today_reports_qs)
    month_summary = _summarize_daily_reports(month_reports_qs)
    year_summary = _summarize_daily_reports(year_reports_qs)

    dashboard_url = reverse("admin_dashboard")
    selected_site_query = f"&site={selected_site.id}" if selected_site else ""

    latest_report = reports_qs.first()
    latest_report_item = None
    if latest_report:
        latest_report_item = {
            "shift": latest_report,
            "employee_name": latest_report.employe.get_full_name() or latest_report.employe.username,
            "site_name": latest_report.site.nom if latest_report.site else "Site inconnu",
            "detail_url": (
                reverse("admin_site_detail", kwargs={"site_id": latest_report.site.id})
                + f"?date_debut={latest_report.date:%Y-%m-%d}&date_fin={latest_report.date:%Y-%m-%d}"
            ) if latest_report.site else "",
            "edit_url": (
                reverse("admin_edit_pointage", kwargs={"site_id": latest_report.site.id, "pointage_id": latest_report.id})
                + f"?next={reverse('admin_daily_report_history')}%3Fmonth%3D{month_start:%Y-%m}{selected_site_query.replace('&', '%26')}"
            ) if latest_report.site else "",
        }

    daily_groups = []
    current_group = None
    for shift in month_reports_qs:
        if current_group is None or current_group["date"] != shift.date:
            current_group = {
                "date": shift.date,
                "label": shift.date.strftime("%A %d/%m/%Y").capitalize(),
                "report_count": 0,
                "amount_total": Decimal("0"),
                "expenses_total": Decimal("0"),
                "net_total": Decimal("0"),
                "employee_names": set(),
                "site_names": set(),
                "entries": [],
            }
            daily_groups.append(current_group)

        employee_name = shift.employe.get_full_name() or shift.employe.username
        amount_total = _to_decimal_amount(shift.total_amount_reported_fc)
        expenses_total = _to_decimal_amount(shift.daily_expenses_total_fc)
        next_query = f"{reverse('admin_daily_report_history')}?month={month_start:%Y-%m}{selected_site_query}"

        current_group["report_count"] += 1
        current_group["amount_total"] += amount_total
        current_group["expenses_total"] += expenses_total
        current_group["net_total"] += amount_total - expenses_total
        current_group["employee_names"].add(employee_name)
        current_group["site_names"].add(shift.site.nom if shift.site else "Site inconnu")
        current_group["entries"].append(
            {
                "shift": shift,
                "employee_name": employee_name,
                "site_name": shift.site.nom if shift.site else "Site inconnu",
                "detail_url": (
                    reverse("admin_site_detail", kwargs={"site_id": shift.site.id})
                    + f"?date_debut={shift.date:%Y-%m-%d}&date_fin={shift.date:%Y-%m-%d}"
                ) if shift.site else "",
                "employee_url": (
                    reverse("admin_site_employee_portal", kwargs={"site_id": shift.site.id, "profile_id": shift.employe.userprofile.id})
                ) if shift.site and hasattr(shift.employe, "userprofile") else "",
                "edit_url": (
                    reverse("admin_edit_pointage", kwargs={"site_id": shift.site.id, "pointage_id": shift.id})
                    + f"?next={next_query}"
                ) if shift.site else "",
                "delete_report_url": (
                    reverse("admin_delete_daily_report", kwargs={"site_id": shift.site.id, "pointage_id": shift.id})
                    + f"?next={next_query}"
                ) if shift.site else "",
            }
        )

    for group in daily_groups:
        group["employee_names"] = ", ".join(sorted(group["employee_names"]))
        group["site_names"] = ", ".join(sorted(group["site_names"]))

    monthly_trend = []
    cursor = month_start
    for _ in range(6):
        cursor_end = cursor.replace(day=calendar.monthrange(cursor.year, cursor.month)[1])
        period_summary = _summarize_daily_reports(
            reports_qs.filter(date__gte=cursor, date__lte=cursor_end)
        )
        monthly_trend.append(
            {
                "month_start": cursor,
                "month_end": cursor_end,
                "label": _month_label(cursor),
                "url": f"{reverse('admin_daily_report_history')}?month={cursor:%Y-%m}{selected_site_query}",
                "is_selected": cursor == month_start,
                **period_summary,
            }
        )
        cursor = _previous_month_start(cursor)

    site_breakdown = []
    for item in (
        month_reports_qs.values("site__id", "site__nom")
        .annotate(
            report_count=Count("id"),
            amount_total=Sum("total_amount_reported_fc"),
            expenses_total=Sum("daily_expenses_total_fc"),
        )
        .order_by("-amount_total", "site__nom")
    ):
        amount_total = _to_decimal_amount(item["amount_total"])
        expenses_total = _to_decimal_amount(item["expenses_total"])
        site_breakdown.append(
            {
                "site_id": item["site__id"],
                "site_name": item["site__nom"],
                "report_count": item["report_count"] or 0,
                "amount_total": amount_total,
                "expenses_total": expenses_total,
                "net_total": amount_total - expenses_total,
            }
        )

    employee_breakdown = []
    for item in (
        month_reports_qs.values("employe__first_name", "employe__last_name", "employe__username", "site__nom")
        .annotate(
            report_count=Count("id"),
            amount_total=Sum("total_amount_reported_fc"),
            expenses_total=Sum("daily_expenses_total_fc"),
        )
        .order_by("-amount_total", "employe__username")[:8]
    ):
        amount_total = _to_decimal_amount(item["amount_total"])
        expenses_total = _to_decimal_amount(item["expenses_total"])
        display_name = " ".join(
            part for part in [item["employe__first_name"], item["employe__last_name"]] if part
        ).strip() or item["employe__username"]
        employee_breakdown.append(
            {
                "employee_name": display_name,
                "site_name": item["site__nom"],
                "report_count": item["report_count"] or 0,
                "amount_total": amount_total,
                "expenses_total": expenses_total,
                "net_total": amount_total - expenses_total,
            }
        )

    return {
        "selected_month": month_start,
        "selected_month_label": _month_label(month_start),
        "selected_month_input": month_start.strftime("%Y-%m"),
        "selected_month_end": month_end,
        "today_summary": today_summary,
        "month_summary": month_summary,
        "year_summary": year_summary,
        "all_time_summary": all_time_summary,
        "daily_groups": daily_groups,
        "monthly_trend": monthly_trend,
        "monthly_trend_max_amount": max((item["amount_total"] for item in monthly_trend), default=Decimal("1")) or Decimal("1"),
        "monthly_trend_max_reports": max((item["report_count"] for item in monthly_trend), default=1) or 1,
        "monthly_trend_max_expenses": max((item["expenses_total"] for item in monthly_trend), default=Decimal("1")) or Decimal("1"),
        "site_breakdown": site_breakdown,
        "employee_breakdown": employee_breakdown,
        "latest_report_item": latest_report_item,
    }


def _build_site_journal_month_bucket(month_start):
    categories = []
    category_map = {}
    for code, label in SiteJournalEntry.CATEGORY_CHOICES:
        bucket = {
            "code": code,
            "label": label,
            "entries": [],
            "entries_count": 0,
            "amount_total": Decimal("0"),
        }
        categories.append(bucket)
        category_map[code] = bucket

    return {
        "month": month_start,
        "month_input": month_start.strftime("%Y-%m"),
        "entries_count": 0,
        "amount_total": Decimal("0"),
        "expense_total": Decimal("0"),
        "expense_count": 0,
        "categories": categories,
        "category_map": category_map,
    }


def _build_site_journal_overview(entries, selected_month):
    month_buckets = {}

    for entry in entries:
        month_start = entry.entry_date.replace(day=1)
        bucket = month_buckets.setdefault(month_start, _build_site_journal_month_bucket(month_start))
        bucket["entries_count"] += 1

        if entry.amount_fc:
            bucket["amount_total"] += entry.amount_fc
            bucket["category_map"][entry.category]["amount_total"] += entry.amount_fc

        if entry.category == "DEPENSE":
            bucket["expense_count"] += 1
            if entry.amount_fc:
                bucket["expense_total"] += entry.amount_fc

        category_bucket = bucket["category_map"][entry.category]
        category_bucket["entries"].append(entry)
        category_bucket["entries_count"] += 1

    selected_bucket = month_buckets.get(selected_month)
    if selected_bucket is None:
        selected_bucket = _build_site_journal_month_bucket(selected_month)
        month_buckets[selected_month] = selected_bucket

    month_summaries = sorted(month_buckets.values(), key=lambda item: item["month"], reverse=True)
    for bucket in month_summaries:
        bucket["non_expense_count"] = bucket["entries_count"] - bucket["expense_count"]
        bucket["active_categories"] = [
            category for category in bucket["categories"]
            if category["entries_count"] > 0
        ]

    return {
        "month_summaries": month_summaries,
        "selected_month_data": selected_bucket,
    }


def _daily_funding_snapshot(site, date_obj, exclude_loss_id=None, exclude_deposit_id=None):
    """
    Calcule les soldes disponibles du jour pour la caisse et la banque.
    """
    cash_flow = CarWash.objects.filter(site=site, date=date_obj).aggregate(total=Sum('montant'))['total'] or Decimal('0')

    deposits_all_qs = DailyBankDeposit.objects.filter(site=site)
    if exclude_deposit_id:
        deposits_all_qs = deposits_all_qs.exclude(id=exclude_deposit_id)

    losses_all_qs = SiteLossEntry.objects.filter(site=site)
    if exclude_loss_id:
        losses_all_qs = losses_all_qs.exclude(id=exclude_loss_id)

    deposits_day_qs = deposits_all_qs.filter(date=date_obj)
    losses_day_qs = losses_all_qs.filter(date=date_obj)

    bank_deposit = deposits_day_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    pertes_caisse = losses_day_qs.filter(funding_source='CAISSE').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    pertes_banque = losses_day_qs.filter(funding_source='BANQUE').aggregate(total=Sum('amount'))['total'] or Decimal('0')

    week_start = date_obj - timedelta(days=date_obj.weekday())
    week_end = week_start + timedelta(days=6)
    bank_week_deposit = deposits_all_qs.filter(
        date__gte=week_start,
        date__lte=week_end,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    pertes_banque_week = losses_all_qs.filter(
        funding_source='BANQUE',
        date__gte=week_start,
        date__lte=week_end,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    bank_total_deposit = deposits_all_qs.filter(date__lte=date_obj).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    pertes_banque_total = losses_all_qs.filter(
        funding_source='BANQUE',
        date__lte=date_obj,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    return {
        'date': date_obj,
        'week_start': week_start,
        'week_end': week_end,
        'cash_flow': cash_flow,
        'bank_deposit': bank_deposit,
        'pertes_caisse': pertes_caisse,
        'pertes_banque': pertes_banque,
        'caisse_available': cash_flow - bank_deposit - pertes_caisse,
        'bank_available': bank_deposit - pertes_banque,
        'bank_week_deposit': bank_week_deposit,
        'pertes_banque_week': pertes_banque_week,
        'bank_week_available': bank_week_deposit - pertes_banque_week,
        'bank_total_deposit': bank_total_deposit,
        'pertes_banque_total': pertes_banque_total,
        'bank_total_available': bank_total_deposit - pertes_banque_total,
    }


def _funding_source_choices_with_balances(snapshot):
    """
    Libellés de source des fonds enrichis avec les soldes disponibles.
    """
    return [
        (
            'CAISSE',
            f"Caisse du jour ({_format_fc_compact(snapshot['caisse_available'])} FC)"
        ),
        (
            'BANQUE',
            (
                "Banque "
                f"(jour: {_format_fc_compact(snapshot['bank_available'])} FC, "
                f"semaine: {_format_fc_compact(snapshot['bank_week_available'])} FC, "
                f"global: {_format_fc_compact(snapshot['bank_total_available'])} FC)"
            )
        ),
    ]


def _render_bank_deposit_form(request, site, date_value, deposit=None, next_url=''):
    """
    Construit le contexte du formulaire de dépôt bancaire avec les soldes du jour.
    """
    if isinstance(date_value, str):
        try:
            date_obj = datetime.strptime(date_value, '%Y-%m-%d').date()
        except ValueError:
            date_obj = timezone.localdate()
    else:
        date_obj = date_value

    if deposit is None:
        deposit = DailyBankDeposit.objects.filter(site=site, date=date_obj).first()

    snapshot = _daily_funding_snapshot(
        site,
        date_obj,
        exclude_deposit_id=deposit.id if deposit else None,
    )
    return render(request, 'admin/add_bank_deposit.html', {
        'site': site,
        'today': date_obj,
        'deposit': deposit,
        'next_url': next_url,
        'funding_snapshot': snapshot,
    })


def _render_site_loss_form(request, site, mode, date_value, next_url='', loss_entry=None):
    """
    Construit le contexte du formulaire de perte avec les soldes du jour.
    """
    if isinstance(date_value, str):
        try:
            date_obj = datetime.strptime(date_value, '%Y-%m-%d').date()
        except ValueError:
            date_obj = timezone.localdate()
    else:
        date_obj = date_value

    snapshot = _daily_funding_snapshot(
        site,
        date_obj,
        exclude_loss_id=loss_entry.id if loss_entry else None,
    )
    return render(request, 'admin/site_loss_form.html', {
        'site': site,
        'mode': mode,
        'loss_entry': loss_entry,
        'loss_categories': SiteLossEntry.CATEGORY_CHOICES,
        'funding_sources': _funding_source_choices_with_balances(snapshot),
        'today': date_obj.strftime('%Y-%m-%d'),
        'next_url': next_url,
        'funding_snapshot': snapshot,
    })


def _build_admin_password_overview(current_user):
    """
    Prépare la liste des comptes dont le mot de passe peut être géré depuis le portail admin.
    """
    managed_users = (
        User.objects.filter(Q(is_superuser=True) | Q(userprofile__isnull=False))
        .select_related("userprofile", "userprofile__site")
        .distinct()
    )

    role_order = {"ADMIN": 0, "MANAGER": 1, "EMPLOYE": 2, "CONTROLE_CAMERA": 3, "AUTRE": 4}
    grouped_accounts = {"ADMIN": [], "MANAGER": [], "EMPLOYE": [], "CONTROLE_CAMERA": [], "AUTRE": []}
    summary = {
        "total_accounts": 0,
        "admin_accounts": 0,
        "manager_accounts": 0,
        "employee_accounts": 0,
        "camera_accounts": 0,
        "active_accounts": 0,
        "pending_accounts": 0,
        "password_notes_recorded": 0,
        "password_notes_missing": 0,
    }
    current_account = None
    credential_notebook_accounts = []

    for managed_user in managed_users:
        profile = getattr(managed_user, "userprofile", None)
        if managed_user.is_superuser or (profile and profile.role == "ADMIN"):
            role_code = "ADMIN"
            role_label = "Administrateur"
        elif profile and profile.role == "MANAGER":
            role_code = "MANAGER"
            role_label = "Manager"
        elif profile and profile.role == "EMPLOYE":
            role_code = "EMPLOYE"
            role_label = "Employé"
        elif profile and profile.role == UserProfile.CAMERA_CONTROLLER_ROLE:
            role_code = UserProfile.CAMERA_CONTROLLER_ROLE
            role_label = "Contrôle caméra"
        else:
            role_code = "AUTRE"
            role_label = "Compte"

        full_name = managed_user.get_full_name().strip() or managed_user.username
        site_name = profile.site.nom if profile and profile.site else "Compte global"
        status_label = "Actif" if managed_user.is_active else "En attente"
        password_reference = profile.password_reference.strip() if profile and profile.password_reference else ""

        account = {
            "user": managed_user,
            "profile": profile,
            "display_name": full_name,
            "username": managed_user.username,
            "email": managed_user.email,
            "role_code": role_code,
            "role_label": role_label,
            "site_name": site_name,
            "site_id": str(profile.site_id) if profile and profile.site_id else "",
            "status_label": status_label,
            "is_active": managed_user.is_active,
            "last_login": managed_user.last_login,
            "is_current_user": current_user and managed_user.id == current_user.id,
            "change_password_url": reverse("admin_change_user_password", kwargs={"user_id": managed_user.id}),
            "update_password_reference_url": reverse("admin_update_password_reference", kwargs={"user_id": managed_user.id}),
            "password_reference": password_reference,
            "has_password_reference": bool(password_reference),
        }

        summary["total_accounts"] += 1
        if managed_user.is_active:
            summary["active_accounts"] += 1
        else:
            summary["pending_accounts"] += 1
        if account["has_password_reference"]:
            summary["password_notes_recorded"] += 1
        else:
            summary["password_notes_missing"] += 1

        if role_code == "ADMIN":
            summary["admin_accounts"] += 1
        elif role_code == "MANAGER":
            summary["manager_accounts"] += 1
        elif role_code == "EMPLOYE":
            summary["employee_accounts"] += 1
        elif role_code == UserProfile.CAMERA_CONTROLLER_ROLE:
            summary["camera_accounts"] += 1
            summary["employee_accounts"] += 1

        credential_notebook_accounts.append(account)

        if account["is_current_user"]:
            current_account = account
            continue

        grouped_accounts[role_code].append(account)

    for role_code, accounts in grouped_accounts.items():
        accounts.sort(
            key=lambda item: (
                item["site_name"].lower(),
                item["display_name"].lower(),
                item["username"].lower(),
            )
        )

    credential_notebook_accounts.sort(
        key=lambda item: (
            0 if item["is_current_user"] else 1,
            role_order.get(item["role_code"], 4),
            item["site_name"].lower(),
            item["display_name"].lower(),
            item["username"].lower(),
        )
    )

    sections = [
        {
            "title": "Administrateurs",
            "accounts": grouped_accounts["ADMIN"],
            "empty_label": "Aucun autre administrateur n'est enregistré.",
        },
        {
            "title": "Managers",
            "accounts": grouped_accounts["MANAGER"],
            "empty_label": "Aucun manager n'est enregistré.",
        },
        {
            "title": "Employés",
            "accounts": grouped_accounts["EMPLOYE"],
            "empty_label": "Aucun employé n'est enregistré.",
        },
        {
            "title": "Contrôle caméra",
            "accounts": grouped_accounts[UserProfile.CAMERA_CONTROLLER_ROLE],
            "empty_label": "Aucun contrôleur caméra n'est enregistré.",
        },
    ]

    if grouped_accounts["AUTRE"]:
        sections.append(
            {
                "title": "Autres comptes",
                "accounts": grouped_accounts["AUTRE"],
                "empty_label": "Aucun autre compte n'est enregistré.",
            }
        )

    return {
        "summary": summary,
        "current_account": current_account,
        "sections": sections,
        "credential_notebook_accounts": credential_notebook_accounts,
    }


def _build_password_creation_actions(request):
    """
    Prépare les accès rapides de création de comptes depuis la page mots de passe.
    """
    next_url = reverse("admin_password_management")
    active_sites = (
        Location.objects.filter(actif=True)
        .annotate(site_staff_count=Count("userprofile", filter=Q(userprofile__role__in=UserProfile.SITE_STAFF_ROLES)))
        .order_by("nom")
    )

    creation_sites = []
    for site in active_sites:
        creation_sites.append(
            {
                "site": site,
                "site_name": site.nom,
                "site_city": site.ville,
                "site_staff_count": site.site_staff_count,
                "camera_create_url": (
                    f"{reverse('admin_add_site_employee', kwargs={'site_id': site.id})}"
                    f"?role={UserProfile.CAMERA_CONTROLLER_ROLE}&next={quote(next_url)}"
                ),
            }
        )

    return {
        "creation_sites": creation_sites,
        "creation_sites_count": len(creation_sites),
    }


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
    date_debut = request.GET.get("date_debut") or today.strftime("%Y-%m-%d")
    date_fin = request.GET.get("date_fin") or date_debut

    try:
        selected_start = datetime.strptime(date_debut, "%Y-%m-%d").date()
    except ValueError:
        selected_start = today
        date_debut = selected_start.strftime("%Y-%m-%d")

    try:
        selected_end = datetime.strptime(date_fin, "%Y-%m-%d").date()
    except ValueError:
        selected_end = selected_start
        date_fin = selected_end.strftime("%Y-%m-%d")

    if selected_end < selected_start:
        selected_start, selected_end = selected_end, selected_start
        date_debut = selected_start.strftime("%Y-%m-%d")
        date_fin = selected_end.strftime("%Y-%m-%d")

    if selected_start == selected_end:
        selected_period_label = f"Le {selected_start:%d/%m/%Y}"
    else:
        selected_period_label = f"Du {selected_start:%d/%m/%Y} au {selected_end:%d/%m/%Y}"

    range_start = timezone.make_aware(datetime.combine(selected_start, datetime.min.time()))
    range_end = timezone.make_aware(datetime.combine(selected_end + timedelta(days=1), datetime.min.time()))

    sites = list(Location.objects.filter(actif=True).order_by("nom"))
    site_ids = [site.id for site in sites]

    employee_counts = {
        item["site"]: item["total"]
        for item in UserProfile.objects.filter(
            site_id__in=site_ids,
            role="EMPLOYE",
            actif=True,
        ).values("site").annotate(total=Count("id"))
    }
    pointage_stats = {
        item["site"]: item
        for item in ShiftDay.objects.filter(
            site_id__in=site_ids,
            date__gte=selected_start,
            date__lte=selected_end,
        ).values("site").annotate(
            presents=Count("id", filter=Q(clock_in_time__isnull=False)),
            rapports_confirmes=Count("id", filter=Q(daily_report_confirmed=True)),
            montant_rapports_jour=Sum(
                "total_amount_reported_fc",
                filter=Q(daily_report_confirmed=True),
            ),
        )
    }
    wash_stats = {
        item["site"]: item
        for item in CarWash.objects.filter(
            site_id__in=site_ids,
            date__gte=selected_start,
            date__lte=selected_end,
        ).values("site").annotate(
            total_lavages=Count("id"),
            chiffre_jour=Sum("montant"),
        )
    }
    issue_range_stats = {
        item["site"]: item["problemes_today"]
        for item in IssueReport.objects.filter(
            site_id__in=site_ids,
            created_at__gte=range_start,
            created_at__lt=range_end,
        ).values("site").annotate(problemes_today=Count("id"))
    }
    open_issue_stats = {
        item["site"]: item["problemes_ouverts"]
        for item in IssueReport.objects.filter(
            site_id__in=site_ids,
            statut__in=["OUVERT", "EN_COURS"],
        ).values("site").annotate(problemes_ouverts=Count("id"))
    }

    sites_stats = []
    for site in sites:
        total_employes = employee_counts.get(site.id, 0)
        pointage_summary = pointage_stats.get(site.id, {})
        wash_summary = wash_stats.get(site.id, {})
        presents = pointage_summary.get("presents", 0)
        chiffre_jour = wash_summary.get("chiffre_jour") or Decimal("0")
        montant_rapports_jour = pointage_summary.get("montant_rapports_jour") or Decimal("0")
        sites_stats.append({
            "site": site,
            "total_employes": total_employes,
            "presents": presents,
            "absents": max(total_employes - presents, 0),
            "total_lavages": wash_summary.get("total_lavages", 0),
            "chiffre_jour": chiffre_jour,
            "montant_rapports_jour": montant_rapports_jour,
            "rapports_confirmes": pointage_summary.get("rapports_confirmes", 0),
            "ecart_rapports": montant_rapports_jour - chiffre_jour,
            "problemes_today": issue_range_stats.get(site.id, 0),
            "problemes_ouverts": open_issue_stats.get(site.id, 0),
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

    recent_daily_reports = []
    dashboard_url = reverse("admin_dashboard")
    for shift in (
        ShiftDay.objects.filter(
            daily_report_confirmed=True,
            date__gte=selected_start,
            date__lte=selected_end,
        )
        .select_related("employe", "site")
        .order_by("-updated_at", "-date")[:12]
    ):
        employee_name = shift.employe.get_full_name() or shift.employe.username
        recent_daily_reports.append({
            "shift": shift,
            "employee_name": employee_name,
            "site_name": shift.site.nom if shift.site else "Site inconnu",
            "is_update": shift.updated_at and shift.created_at and shift.updated_at > (shift.created_at + timedelta(seconds=5)),
            "detail_url": reverse("admin_site_detail", kwargs={"site_id": shift.site.id}) + f"?date_debut={shift.date:%Y-%m-%d}&date_fin={shift.date:%Y-%m-%d}" if shift.site else "",
            "employee_url": reverse("admin_site_employee_portal", kwargs={"site_id": shift.site.id, "profile_id": shift.employe.userprofile.id})
            if shift.site and hasattr(shift.employe, "userprofile") else "",
            "edit_url": reverse("admin_edit_pointage", kwargs={"site_id": shift.site.id, "pointage_id": shift.id}) + f"?next={dashboard_url}"
            if shift.site else "",
            "delete_report_url": reverse("admin_delete_daily_report", kwargs={"site_id": shift.site.id, "pointage_id": shift.id}) + f"?next={dashboard_url}"
            if shift.site else "",
        })

    selected_water_month = _normalize_month_start(selected_start)
    water_purchases_month_qs = SiteWaterPurchase.objects.filter(
        site__actif=True,
        billing_month=selected_water_month,
    ).select_related("site", "supplier").order_by("-purchase_date", "-created_at")
    recent_water_purchases = list(
        SiteWaterPurchase.objects.filter(site__actif=True)
        .select_related("site", "supplier")
        .order_by("-billing_month", "-purchase_date", "-created_at")[:6]
    )
    current_water_supplier = get_default_water_supplier()
    water_purchase_summary = {
        "selected_month": selected_water_month,
        "month_total": water_purchases_month_qs.aggregate(total=Sum("amount_fc"))["total"] or Decimal("0"),
        "month_count": water_purchases_month_qs.count(),
        "current_supplier": current_water_supplier,
        "site_breakdown": list(
            water_purchases_month_qs.values("site__nom")
            .annotate(total=Sum("amount_fc"), count=Count("id"))
            .order_by("-total", "site__nom")
        ),
    }
    password_overview = _build_admin_password_overview(user)

    context = {
        'sites_stats': sites_stats,
        'today': today,
        'date_debut': date_debut,
        'date_fin': date_fin,
        'selected_period_label': selected_period_label,
        'pending_account_requests': pending_account_requests,
        'pending_account_requests_count': len(pending_account_requests),
        'recent_daily_reports': recent_daily_reports,
        'recent_daily_reports_count': len(recent_daily_reports),
        'recent_water_purchases': recent_water_purchases,
        'water_purchase_summary': water_purchase_summary,
        'password_summary': password_overview["summary"],
    }

    mark_admin_inbox_seen(user)

    return render(request, 'admin/dashboard.html', context)


@login_required
@no_cache_view
def admin_messages(request):
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    reminder_form = AdminReminderForm()
    if request.method == "POST" and request.POST.get("action") == "create_admin_reminder":
        reminder_form = AdminReminderForm(request.POST)
        if reminder_form.is_valid():
            reminder = reminder_form.save(commit=False)
            reminder.created_by = user
            reminder.save()
            AuditLog.log(
                user=user,
                action="CREER",
                description=f"Rappel admin ajouté: {reminder.title}",
                content_object=reminder,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )
            messages.success(request, "Rappel ajouté à la page Messages.")
            return redirect(reverse("admin_messages"))
        messages.error(request, "Impossible d'ajouter ce rappel. Vérifiez les champs du formulaire.")

    today = timezone.localdate()
    reminders_snapshot = _build_admin_reminders_snapshot(today)
    context = {
        "today": today,
        "admin_reminder_form": reminder_form,
        "admin_manual_reminders": reminders_snapshot["manual_reminders"],
        "admin_upcoming_birthdays": reminders_snapshot["upcoming_birthdays"],
        "admin_reminder_summary": reminders_snapshot["summary"],
    }
    mark_admin_messages_seen(user)
    return render(request, "admin/messages.html", context)


@login_required
@no_cache_view
@require_http_methods(["POST"])
def admin_resolve_reminder(request, reminder_id):
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    reminder = get_object_or_404(AdminReminder, id=reminder_id, is_resolved=False)
    reminder.is_resolved = True
    reminder.resolved_at = timezone.now()
    reminder.save(update_fields=["is_resolved", "resolved_at", "updated_at"])

    AuditLog.log(
        user=user,
        action="MODIFIER",
        description=f"Rappel admin traité: {reminder.title}",
        content_object=reminder,
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    messages.success(request, "Rappel marqué comme traité.")
    return redirect(reverse('admin_messages'))


@login_required
@no_cache_view
@require_http_methods(["POST"])
def admin_delete_reminder(request, reminder_id):
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    reminder = get_object_or_404(AdminReminder, id=reminder_id)
    reminder_title = reminder.title
    reminder.delete()

    AuditLog.log(
        user=user,
        action="SUPPRIMER",
        description=f"Rappel admin supprimé: {reminder_title}",
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    messages.success(request, "Rappel supprimé.")
    return redirect(reverse('admin_messages'))


@login_required
@no_cache_view
def admin_daily_report_history(request):
    """
    Historique complet des rapports de fin de journée pour l'admin.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    today = timezone.localdate()
    selected_month = _parse_month_filter(request.GET.get("month"))
    active_sites = list(Location.objects.filter(actif=True).order_by("nom"))
    site_param = (request.GET.get("site") or "").strip()
    selected_site = next((site for site in active_sites if str(site.id) == site_param), None)

    history = _build_admin_daily_report_history(selected_month, selected_site=selected_site)
    previous_month = _previous_month_start(selected_month)
    next_month = _next_month_start(selected_month)

    context = {
        "today": today,
        "active_sites": active_sites,
        "selected_site": selected_site,
        "selected_site_id": str(selected_site.id) if selected_site else "",
        "previous_month_input": previous_month.strftime("%Y-%m"),
        "next_month_input": next_month.strftime("%Y-%m"),
        "is_current_month": selected_month == _normalize_month_start(today),
        **history,
    }

    mark_admin_inbox_seen(user)

    return render(request, "admin/daily_report_history.html", context)


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
def admin_password_management(request):
    """
    Vue centrale de gestion des mots de passe des comptes du portail.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    password_overview = _build_admin_password_overview(user)
    creation_actions = _build_password_creation_actions(request)

    return render(
        request,
        "admin/password_management.html",
        {
            "password_summary": password_overview["summary"],
            "current_account": password_overview["current_account"],
            "password_sections": password_overview["sections"],
            "credential_notebook_accounts": password_overview["credential_notebook_accounts"],
            "password_creation_sites": creation_actions["creation_sites"],
            "password_creation_sites_count": creation_actions["creation_sites_count"],
        },
    )


@login_required
@no_cache_view
@require_http_methods(["POST"])
def admin_update_password_reference(request, user_id):
    """
    Mémorise visiblement un mot de passe dans le bloc-notes admin sans modifier le vrai mot de passe du compte.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette action est réservée aux administrateurs.")
        return redirect("dashboard")

    target_user = get_object_or_404(
        User.objects.filter(Q(is_superuser=True) | Q(userprofile__isnull=False)).distinct(),
        id=user_id,
    )
    form = AdminPasswordReferenceForm(request.POST)
    if form.is_valid():
        profile, _ = UserProfile.objects.get_or_create(user=target_user)
        profile.set_password_reference(form.cleaned_data["password_reference"])

        AuditLog.log(
            user=request.user,
            action="MODIFIER",
            description=f"Mémo de mot de passe mis à jour pour le compte {target_user.username}",
            content_object=target_user,
            donnees_apres={
                "username": target_user.username,
                "password_reference_recorded": bool(profile.password_reference),
            },
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        if profile.password_reference:
            messages.success(
                request,
                f'Mot de passe visible mis à jour pour "{target_user.get_full_name() or target_user.username}".',
            )
        else:
            messages.success(
                request,
                f'Mémo de mot de passe vidé pour "{target_user.get_full_name() or target_user.username}".',
            )
    else:
        messages.error(request, "Impossible d'enregistrer ce mémo de mot de passe.")

    return redirect("admin_password_management")


@login_required
@no_cache_view
def admin_change_user_password(request, user_id):
    """
    Permet à un administrateur de redéfinir son propre mot de passe ou celui d'un autre compte.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    target_user = get_object_or_404(
        User.objects.filter(Q(is_superuser=True) | Q(userprofile__isnull=False)).distinct(),
        id=user_id,
    )
    target_profile = getattr(target_user, "userprofile", None)
    target_site = target_profile.site if target_profile else None

    if request.method == "POST":
        form = AdminPasswordManagementForm(request.POST)
        if form.is_valid():
            form.save(target_user)
            if target_user.id == user.id:
                update_session_auth_hash(request, target_user)

            AuditLog.log(
                user=request.user,
                action="MODIFIER",
                description=f"Mot de passe modifié pour le compte {target_user.username}",
                content_object=target_user,
                donnees_apres={
                    "username": target_user.username,
                    "role": target_profile.role if target_profile else "ADMIN",
                    "site": target_site.nom if target_site else "",
                },
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            messages.success(
                request,
                f'Mot de passe mis à jour pour "{target_user.get_full_name() or target_user.username}".',
            )
            return redirect("admin_password_management")
    else:
        form = AdminPasswordManagementForm()

    target_role_label = "Administrateur"
    if target_profile and not target_user.is_superuser:
        target_role_label = target_profile.get_role_display()

    return render(
        request,
        "admin/change_user_password.html",
        {
            "form": form,
            "target_user": target_user,
            "target_profile": target_profile,
            "target_site": target_site,
            "target_role_label": target_role_label,
            "is_self_change": target_user.id == user.id,
        },
    )


def _build_admin_water_purchase_context(selected_month, form, supplier_form):
    today = timezone.localdate()
    purchase_qs = (
        SiteWaterPurchase.objects.filter(site__actif=True, billing_month=selected_month)
        .select_related("site", "supplier", "created_by", "paid_by")
        .order_by("-purchase_date", "-created_at")
    )
    purchases = list(purchase_qs)

    month_total = purchase_qs.aggregate(total=Sum("amount_fc"))["total"] or Decimal("0")
    month_count = len(purchases)
    payment_summary = purchase_qs.aggregate(
        paid_total=Sum("amount_fc", filter=Q(paid_at__isnull=False)),
        paid_count=Count("id", filter=Q(paid_at__isnull=False)),
        unpaid_total=Sum("amount_fc", filter=Q(paid_at__isnull=True)),
        unpaid_count=Count("id", filter=Q(paid_at__isnull=True)),
    )
    month_paid_total = payment_summary["paid_total"] or Decimal("0")
    month_paid_count = payment_summary["paid_count"] or 0
    month_unpaid_total = payment_summary["unpaid_total"] or Decimal("0")
    month_unpaid_count = payment_summary["unpaid_count"] or 0
    default_supplier = get_default_water_supplier()
    active_suppliers = list(
        WaterSupplier.objects.filter(is_active=True)
        .order_by("-is_default", "name")
    )
    all_suppliers = list(
        WaterSupplier.objects.order_by("-is_default", "-is_active", "name")
    )
    by_site = list(
        purchase_qs.values("site__nom")
        .annotate(total=Sum("amount_fc"), count=Count("id"))
        .order_by("-total", "site__nom")
    )
    supplier_breakdown = list(
        purchase_qs.values("supplier_id", "supplier__name")
        .annotate(
            total=Sum("amount_fc"),
            count=Count("id"),
            paid_total=Sum("amount_fc", filter=Q(paid_at__isnull=False)),
            paid_count=Count("id", filter=Q(paid_at__isnull=False)),
            unpaid_total=Sum("amount_fc", filter=Q(paid_at__isnull=True)),
            unpaid_count=Count("id", filter=Q(paid_at__isnull=True)),
            last_paid_at=Max("paid_at"),
        )
        .order_by("-total", "supplier__name")
    )
    average_purchase = (month_total / month_count) if month_count else Decimal("0")
    default_amount = get_water_purchase_default_amount(selected_month, supplier=default_supplier)
    selected_sites_count = len(by_site)
    previous_month = _previous_month_start(selected_month)
    previous_month_total = (
        SiteWaterPurchase.objects.filter(site__actif=True, billing_month=previous_month)
        .aggregate(total=Sum("amount_fc"))["total"]
        or Decimal("0")
    )
    previous_month_count = SiteWaterPurchase.objects.filter(
        site__actif=True,
        billing_month=previous_month,
    ).count()
    month_total_delta = month_total - previous_month_total
    month_last_day = date(
        selected_month.year,
        selected_month.month,
        calendar.monthrange(selected_month.year, selected_month.month)[1],
    )
    purchases_by_reporting_date = {}
    general_breakdown = {
        "label": "General du mois",
        "count": 0,
        "total": Decimal("0"),
        "is_active": False,
        "bar_width": 0,
    }
    for purchase in purchases:
        reporting_week_date = purchase.get_reporting_week_date()
        purchase.reporting_week_date_resolved = reporting_week_date
        if reporting_week_date:
            week_start, week_end = _water_week_bounds_for_month(selected_month, reporting_week_date)
            purchase.reporting_label = (
                f"Semaine du {week_start.strftime('%d/%m')} au {week_end.strftime('%d/%m')}"
                if week_start and week_end
                else "Semaine du mois"
            )
            purchase.reporting_note = (
                "Semaine choisie manuellement par l'administrateur."
                if purchase.reporting_week_date and _date_is_in_month(purchase.reporting_week_date, purchase.billing_month)
                else "Imputation basee sur la date reelle du remplissage."
            )
            bucket = purchases_by_reporting_date.setdefault(
                reporting_week_date,
                {"count": 0, "total": Decimal("0")},
            )
            bucket["count"] += 1
            bucket["total"] += purchase.amount_fc or Decimal("0")
        else:
            purchase.reporting_label = "General du mois"
            purchase.reporting_note = "Non rattache a une semaine precise du mois facture."
            general_breakdown["count"] += 1
            general_breakdown["total"] += purchase.amount_fc or Decimal("0")

    general_breakdown["is_active"] = general_breakdown["count"] > 0
    weekly_breakdown = []
    week_cursor = selected_month
    while week_cursor <= month_last_day:
        week_end = min(week_cursor + timedelta(days=(6 - week_cursor.weekday())), month_last_day)
        week_count = 0
        week_total = Decimal("0")
        day_cursor = week_cursor
        while day_cursor <= week_end:
            day_data = purchases_by_reporting_date.get(day_cursor)
            if day_data:
                week_count += day_data["count"]
                week_total += day_data["total"] or Decimal("0")
            day_cursor += timedelta(days=1)
        weekly_breakdown.append(
            {
                "week_start": week_cursor,
                "week_end": week_end,
                "count": week_count,
                "total": week_total,
                "label": f"Semaine du {week_cursor.strftime('%d/%m')} au {week_end.strftime('%d/%m')}",
                "is_active": week_count > 0,
            }
        )
        week_cursor = week_end + timedelta(days=1)
    max_assignment_count = max(
        [general_breakdown["count"]] + [item["count"] for item in weekly_breakdown],
        default=0,
    )
    for item in weekly_breakdown:
        item["bar_width"] = int((item["count"] / max_assignment_count) * 100) if max_assignment_count else 0
    general_breakdown["bar_width"] = (
        int((general_breakdown["count"] / max_assignment_count) * 100) if max_assignment_count else 0
    )
    monthly_history = list(
        SiteWaterPurchase.objects.filter(site__actif=True)
        .values("billing_month")
        .annotate(
            total=Sum("amount_fc"),
            count=Count("id"),
            site_count=Count("site", distinct=True),
        )
        .order_by("-billing_month")[:6]
    )
    max_history_total = max((item["total"] or Decimal("0") for item in monthly_history), default=Decimal("0"))
    for item in monthly_history:
        item_total = item["total"] or Decimal("0")
        item["label"] = _month_label(item["billing_month"])
        item["average_amount"] = (item_total / item["count"]) if item["count"] else Decimal("0")
        item["bar_width"] = int((item_total / max_history_total) * 100) if max_history_total else 0
        item["is_selected"] = item["billing_month"] == selected_month
    for item in by_site:
        item_total = item["total"] or Decimal("0")
        item["bar_width"] = int((item_total / month_total) * 100) if month_total else 0
    for item in supplier_breakdown:
        item_total = item["total"] or Decimal("0")
        item["paid_total"] = item["paid_total"] or Decimal("0")
        item["paid_count"] = item["paid_count"] or 0
        item["unpaid_total"] = item["unpaid_total"] or Decimal("0")
        item["unpaid_count"] = item["unpaid_count"] or 0
        item["is_fully_paid"] = item["count"] > 0 and item["unpaid_count"] == 0
        item["is_partially_paid"] = item["paid_count"] > 0 and item["unpaid_count"] > 0
        item["pay_url"] = reverse("admin_mark_water_supplier_paid", kwargs={"supplier_id": item["supplier_id"]})
        item["bar_width"] = int((item_total / month_total) * 100) if month_total else 0

    supplier_usage_map = {
        item["supplier_id"]: {
            "count": item["count"] or 0,
            "total": item["total"] or Decimal("0"),
            "paid_total": item["paid_total"] or Decimal("0"),
            "unpaid_total": item["unpaid_total"] or Decimal("0"),
        }
        for item in purchase_qs.values("supplier_id").annotate(
            count=Count("id"),
            total=Sum("amount_fc"),
            paid_total=Sum("amount_fc", filter=Q(paid_at__isnull=False)),
            unpaid_total=Sum("amount_fc", filter=Q(paid_at__isnull=True)),
        )
    }
    supplier_catalog = [
        {
            "supplier": supplier,
            "month_count": supplier_usage_map.get(supplier.id, {}).get("count", 0),
            "month_total": supplier_usage_map.get(supplier.id, {}).get("total", Decimal("0")),
            "month_paid_total": supplier_usage_map.get(supplier.id, {}).get("paid_total", Decimal("0")),
            "month_unpaid_total": supplier_usage_map.get(supplier.id, {}).get("unpaid_total", Decimal("0")),
        }
        for supplier in all_suppliers
    ]

    site_leader = by_site[0] if by_site else None
    supplier_rate_map = {
        str(supplier.pk): {
            "name": supplier.name,
            "amount_fc": f"{supplier.price_per_tank_fc:.2f}",
            "is_default": supplier.is_default,
        }
        for supplier in active_suppliers
    }

    return {
        "form": form,
        "supplier_form": supplier_form,
        "purchases": purchases[:30],
        "today": today,
        "selected_month": selected_month,
        "selected_month_input": selected_month.strftime("%Y-%m"),
        "month_total": month_total,
        "month_count": month_count,
        "month_paid_total": month_paid_total,
        "month_paid_count": month_paid_count,
        "month_unpaid_total": month_unpaid_total,
        "month_unpaid_count": month_unpaid_count,
        "site_breakdown": by_site,
        "supplier_breakdown": supplier_breakdown,
        "average_purchase": average_purchase,
        "default_amount": default_amount,
        "default_supplier": default_supplier,
        "active_suppliers": active_suppliers,
        "supplier_catalog": supplier_catalog,
        "selected_sites_count": selected_sites_count,
        "previous_month": previous_month,
        "previous_month_total": previous_month_total,
        "previous_month_count": previous_month_count,
        "month_total_delta": month_total_delta,
        "weekly_breakdown": weekly_breakdown,
        "general_breakdown": general_breakdown,
        "monthly_history": monthly_history,
        "site_leader": site_leader,
        "supplier_rate_map": supplier_rate_map,
    }


@login_required
@no_cache_view
def admin_water_purchases(request):
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    selected_month = _parse_month_filter(request.GET.get("month"))

    if request.method == "POST":
        submitted_form = request.POST.get("form_type")
        if submitted_form == "supplier":
            form = SiteWaterPurchaseForm(initial={"billing_month": selected_month})
            supplier_form = WaterSupplierForm(request.POST, prefix="supplier_setup")
            if supplier_form.is_valid():
                supplier = supplier_form.save()
                messages.success(request, f'Le fournisseur "{supplier.name}" a été ajouté.')
                return redirect(f"{reverse('admin_water_purchases')}?month={selected_month.strftime('%Y-%m')}")
        else:
            form = SiteWaterPurchaseForm(request.POST)
            supplier_form = WaterSupplierForm(prefix="supplier_setup")
            if form.is_valid():
                purchase = form.save(commit=False)
                purchase.created_by = user
                purchase.save()
                messages.success(request, "L'achat d'eau a été enregistré.")
                month_query = purchase.billing_month.strftime("%Y-%m")
                return redirect(f"{reverse('admin_water_purchases')}?month={month_query}")
    else:
        form = SiteWaterPurchaseForm(initial={"billing_month": selected_month})
        supplier_form = WaterSupplierForm(prefix="supplier_setup")

    return render(
        request,
        "admin/water_purchases.html",
        _build_admin_water_purchase_context(
            selected_month=selected_month,
            form=form,
            supplier_form=supplier_form,
        ),
    )


@login_required
@no_cache_view
def admin_edit_water_purchase(request, purchase_id):
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    purchase = get_object_or_404(SiteWaterPurchase, id=purchase_id)
    if request.method == "POST":
        form = SiteWaterPurchaseForm(request.POST, instance=purchase)
        if form.is_valid():
            updated_purchase = form.save()
            messages.success(request, "L'achat d'eau a été mis à jour.")
            month_query = updated_purchase.billing_month.strftime("%Y-%m")
            return redirect(f"{reverse('admin_water_purchases')}?month={month_query}")
    else:
        form = SiteWaterPurchaseForm(instance=purchase)

    return render(
        request,
        "admin/edit_water_purchase.html",
        {
            "purchase": purchase,
            "form": form,
        },
    )


@login_required
@no_cache_view
def admin_move_water_purchase(request, purchase_id):
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Acces refuse. Cette page est reservee aux administrateurs.")
        return redirect("dashboard")

    purchase = get_object_or_404(SiteWaterPurchase, id=purchase_id)
    month_query = request.GET.get("month") or purchase.billing_month.strftime("%Y-%m")
    current_reporting_week_date = purchase.get_reporting_week_date()
    current_reporting_label = "General du mois"
    if current_reporting_week_date:
        week_start, week_end = _water_week_bounds_for_month(purchase.billing_month, current_reporting_week_date)
        if week_start and week_end:
            current_reporting_label = (
                f"Semaine du {week_start.strftime('%d/%m')} au {week_end.strftime('%d/%m')}"
            )

    if request.method == "POST":
        form = SiteWaterPurchaseMoveForm(request.POST, purchase_instance=purchase)
        if form.is_valid():
            moved_purchase = form.save(purchase)
            messages.success(request, "L'achat d'eau a ete migre vers le nouveau mois/placement.")
            destination_month = moved_purchase.billing_month.strftime("%Y-%m")
            return redirect(f"{reverse('admin_water_purchases')}?month={destination_month}")
    else:
        form = SiteWaterPurchaseMoveForm(purchase_instance=purchase)

    return render(
        request,
        "admin/move_water_purchase.html",
        {
            "purchase": purchase,
            "form": form,
            "month_query": month_query,
            "current_reporting_label": current_reporting_label,
        },
    )


@login_required
@no_cache_view
def admin_edit_water_supplier(request, supplier_id):
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    selected_month = _parse_month_filter(request.GET.get("month"))
    supplier = get_object_or_404(WaterSupplier, id=supplier_id)

    if request.method == "POST":
        form = WaterSupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            updated_supplier = form.save()
            messages.success(request, f'Le fournisseur "{updated_supplier.name}" a été mis à jour.')
            return redirect(
                f"{reverse('admin_water_purchases')}?month={selected_month.strftime('%Y-%m')}"
            )
    else:
        form = WaterSupplierForm(instance=supplier)

    monthly_usage = supplier.water_purchases.filter(billing_month=selected_month).aggregate(
        count=Count("id"),
        total=Sum("amount_fc"),
    )
    total_usage = supplier.water_purchases.aggregate(
        count=Count("id"),
        total=Sum("amount_fc"),
    )

    return render(
        request,
        "admin/edit_water_supplier.html",
        {
            "supplier": supplier,
            "form": form,
            "selected_month": selected_month,
            "selected_month_input": selected_month.strftime("%Y-%m"),
            "monthly_usage_count": monthly_usage["count"] or 0,
            "monthly_usage_total": monthly_usage["total"] or Decimal("0"),
            "total_usage_count": total_usage["count"] or 0,
            "total_usage_total": total_usage["total"] or Decimal("0"),
        },
    )


@login_required
@require_http_methods(["POST"])
@no_cache_view
def admin_mark_water_supplier_paid(request, supplier_id):
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette action est réservée aux administrateurs.")
        return redirect("dashboard")

    selected_month = _parse_month_filter(request.GET.get("month") or request.POST.get("month"))
    supplier = get_object_or_404(WaterSupplier, id=supplier_id)
    month_query = selected_month.strftime("%Y-%m")
    month_purchases = SiteWaterPurchase.objects.filter(
        site__actif=True,
        billing_month=selected_month,
        supplier=supplier,
    )
    payment_snapshot = month_purchases.aggregate(
        total=Sum("amount_fc"),
        count=Count("id"),
        unpaid_total=Sum("amount_fc", filter=Q(paid_at__isnull=True)),
        unpaid_count=Count("id", filter=Q(paid_at__isnull=True)),
    )
    purchase_count = payment_snapshot["count"] or 0
    unpaid_total = payment_snapshot["unpaid_total"] or Decimal("0")
    unpaid_count = payment_snapshot["unpaid_count"] or 0

    if purchase_count == 0:
        messages.error(
            request,
            f'Aucun achat d’eau n’est enregistré pour "{supplier.name}" sur {selected_month.strftime("%m/%Y")}.',
        )
        return redirect(f"{reverse('admin_water_purchases')}?month={month_query}")

    if unpaid_count == 0:
        messages.info(
            request,
            f'Le fournisseur "{supplier.name}" est déjà soldé pour {selected_month.strftime("%m/%Y")}.',
        )
        return redirect(f"{reverse('admin_water_purchases')}?month={month_query}")

    payment_time = timezone.now()
    month_purchases.filter(paid_at__isnull=True).update(
        paid_at=payment_time,
        paid_by=user,
        updated_at=payment_time,
    )

    AuditLog.log(
        user=user,
        action="MODIFIER",
        description=(
            f'Paiement du fournisseur d’eau "{supplier.name}" '
            f'pour {selected_month.strftime("%m/%Y")}'
        ),
        content_object=supplier,
        donnees_apres={
            "billing_month": selected_month.isoformat(),
            "paid_purchase_count": unpaid_count,
            "paid_total_fc": str(unpaid_total),
        },
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )

    messages.success(
        request,
        (
            f'Le fournisseur "{supplier.name}" a été marqué payé pour '
            f'{selected_month.strftime("%m/%Y")}. Le reste à payer du mois a été mis à jour.'
        ),
    )
    return redirect(f"{reverse('admin_water_purchases')}?month={month_query}")


@login_required
@no_cache_view
def admin_delete_water_purchase(request, purchase_id):
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    purchase = get_object_or_404(SiteWaterPurchase, id=purchase_id)
    next_url = _safe_next_url(request) or ''
    if request.method == "POST":
        month_query = purchase.billing_month.strftime("%Y-%m")
        redirect_url = _safe_next_url(request)
        purchase.delete()
        messages.success(request, "L'achat d'eau a été supprimé.")
        if redirect_url:
            return redirect(redirect_url)
        return redirect(f"{reverse('admin_water_purchases')}?month={month_query}")

    return render(
        request,
        "admin/delete_water_purchase.html",
        {
            "purchase": purchase,
            "next_url": next_url,
        },
    )


def admin_delete_fuel_purchase(request, purchase_id):
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    purchase = get_object_or_404(SiteFuelPurchase, id=purchase_id)
    next_url = _safe_next_url(request) or ''
    if request.method == "POST":
        redirect_url = _safe_next_url(request)
        deleted_date = purchase.purchase_date
        deleted_site = purchase.site
        purchase.delete()
        messages.success(request, "L'achat de carburant a été supprimé.")
        if redirect_url:
            return redirect(redirect_url)
        return _redirect_to_admin_site_detail(request, deleted_site, date_obj=deleted_date)

    return render(
        request,
        "admin/delete_fuel_purchase.html",
        {
            "purchase": purchase,
            "next_url": next_url,
        },
    )


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
    week_anchor_param = request.GET.get('week_anchor')
    filter_today = request.GET.get('filter_today', 'false') == 'true'
    selected_single_date = None  # Date unique sélectionnée pour affichage détaillé
    selected_week_anchor = today
    parsed_date_debut = None
    parsed_date_fin = None

    if date_debut:
        try:
            parsed_date_debut = datetime.strptime(date_debut, '%Y-%m-%d').date()
        except ValueError:
            parsed_date_debut = None

    if date_fin:
        try:
            parsed_date_fin = datetime.strptime(date_fin, '%Y-%m-%d').date()
        except ValueError:
            parsed_date_fin = None

    if week_anchor_param:
        try:
            selected_week_anchor = datetime.strptime(week_anchor_param, '%Y-%m-%d').date()
        except ValueError:
            selected_week_anchor = today
    
    # Par défaut, charger aujourd'hui uniquement pour garder la page réactive.
    if filter_today:
        lavages_query = CarWash.objects.filter(site=site, date=today)
        selected_date_start = today
        selected_date_end = today
        selected_single_date = today
        selected_week_anchor = today
    elif parsed_date_debut and parsed_date_fin and parsed_date_debut == parsed_date_fin:
        # Une seule date sélectionnée - affichage détaillé
        selected_single_date = parsed_date_debut
        lavages_query = CarWash.objects.filter(site=site, date=selected_single_date)
        selected_date_start = selected_single_date
        selected_date_end = selected_single_date
        selected_week_anchor = selected_single_date
    elif parsed_date_debut or parsed_date_fin:
        lavages_query = CarWash.objects.filter(site=site)
        if parsed_date_debut:
            lavages_query = lavages_query.filter(date__gte=parsed_date_debut)
            selected_date_start = parsed_date_debut
        else:
            selected_date_start = None
        if parsed_date_fin:
            lavages_query = lavages_query.filter(date__lte=parsed_date_fin)
            selected_date_end = parsed_date_fin
        else:
            selected_date_end = None
    else:
        lavages_query = CarWash.objects.filter(site=site, date=today)
        selected_date_start = today
        selected_date_end = today
        selected_single_date = today
        selected_week_anchor = today

    lavages_query = lavages_query.select_related("employe").annotate(
        photo_count_value=Count("photos", distinct=True),
    )
    
    # Récupérer les lavages triés par date décroissante et paginer la table.
    lavages_all_qs = lavages_query.order_by('-date', '-created_at')
    lavages_all = paginate_queryset(request, lavages_all_qs, per_page=20, page_param="lavages_page")
    total_lavages = lavages_all_qs.count()
    chiffre_periode = lavages_all_qs.aggregate(total=Sum('montant'))['total'] or 0
    
    photos_lavages_qs = (
        CarWashPhoto.objects.filter(lavage_id__in=lavages_query.values("id"))
        .select_related("lavage", "lavage__employe")
        .order_by("-lavage__date", "-uploaded_at")
    )
    photos_lavages = paginate_queryset(request, photos_lavages_qs, per_page=24, page_param="photos_page")
    photos_lavages_total = photos_lavages_qs.count()
    
    # Déterminer la date pour les détails quotidiens (aujourd'hui ou date sélectionnée)
    detail_date = selected_single_date if selected_single_date else selected_week_anchor
    
    # Problèmes du jour sélectionné
    problemes_date = (
        IssueReport.objects.filter(site=site, created_at__date=detail_date)
        .select_related('employe', 'traite_par')
        .order_by('-created_at')
    )
    
    # Problèmes ouverts (tous statuts, toutes dates)
    problemes_ouverts = IssueReport.objects.filter(
        site=site,
        statut__in=['OUVERT', 'EN_COURS']
    ).select_related("employe", "traite_par").order_by('-created_at')
    
    lavages_date = (
        CarWash.objects.filter(site=site, date=detail_date)
        .select_related('employe')
        .annotate(photo_count_value=Count("photos", distinct=True))
        .order_by('-created_at')
    )
    pointages_date_qs = ShiftDay.objects.filter(site=site, date=detail_date).select_related('employe').order_by('-clock_in_time')
    reports_date = (
        ShiftDay.objects.filter(site=site, date=detail_date, daily_report_confirmed=True)
        .select_related('employe')
        .order_by('-updated_at')
    )
    water_purchases_date = (
        SiteWaterPurchase.objects.filter(site=site, purchase_date=detail_date)
        .select_related('created_by', 'supplier')
        .order_by('-created_at')
    )
    fuel_purchases_date = (
        SiteFuelPurchase.objects.filter(site=site, purchase_date=detail_date)
        .select_related('created_by')
        .order_by('-created_at')
    )
    journal_entries_date = (
        SiteJournalEntry.objects.filter(site=site, entry_date=detail_date)
        .select_related('created_by')
        .order_by('-created_at')
    )

    # Employés du site
    employes_site = UserProfile.objects.filter(
        site=site,
        role='EMPLOYE',
        actif=True
    ).select_related('user').order_by('user__first_name', 'user__last_name', 'user__username')

    # Pointages de la date sélectionnée avec calcul de durée et statut de présence
    pointages_by_employee = {pointage.employe_id: pointage for pointage in pointages_date_qs}
    pointages_with_duration = []
    seen_employee_ids = set()

    def _format_pointage_duration(pointage):
        if not pointage or not pointage.clock_in_time or not pointage.clock_out_time:
            return None
        duration = pointage.clock_out_time - pointage.clock_in_time
        total_seconds = int(duration.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}h{minutes:02d}min"

    def _append_pointage_row(employee, pointage=None):
        pointages_with_duration.append({
            'employee': employee,
            'pointage': pointage,
            'duration': _format_pointage_duration(pointage),
            'attendance_status': (
                pointage.get_clock_in_attendance_status()
                if pointage else
                get_clock_in_status(detail_date, None)
            ),
            'clock_out_status': (
                pointage.get_clock_out_attendance_status()
                if pointage else
                get_clock_out_status(detail_date, None)
            ),
        })

    for profile in employes_site:
        seen_employee_ids.add(profile.user_id)
        _append_pointage_row(profile.user, pointages_by_employee.get(profile.user_id))

    for pointage in pointages_date_qs:
        if pointage.employe_id in seen_employee_ids:
            continue
        seen_employee_ids.add(pointage.employe_id)
        _append_pointage_row(pointage.employe, pointage)

    presents = sum(
        1
        for item in pointages_with_duration
        if item['attendance_status']['code'] in {'PRESENT', 'LATE'}
    )

    # Statistiques par employé pour la date sélectionnée
    lavages_by_employee = {}
    if selected_single_date:
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
    bank_deposit_date = DailyBankDeposit.objects.filter(site=site, date=detail_date).select_related('created_by').first()
    bank_deposit_amount_date = bank_deposit_date.amount if bank_deposit_date else 0

    # Pertes de la date sélectionnée
    losses_date_qs = (
        SiteLossEntry.objects.filter(site=site, date=detail_date)
        .select_related('created_by')
        .order_by('-created_at')
    )
    pertes_date_total = losses_date_qs.aggregate(total=Sum('amount'))['total'] or 0
    pertes_date_caisse = losses_date_qs.filter(funding_source='CAISSE').aggregate(total=Sum('amount'))['total'] or 0
    pertes_date_banque = losses_date_qs.filter(funding_source='BANQUE').aggregate(total=Sum('amount'))['total'] or 0

    # Calculer le cash flow pour la date sélectionnée
    chiffre_date = CarWash.objects.filter(site=site, date=detail_date).aggregate(total=Sum('montant'))['total'] or 0
    rapports_date_qs = ShiftDay.objects.filter(site=site, date=detail_date, daily_report_confirmed=True)
    montant_rapports_date = rapports_date_qs.aggregate(total=Sum('total_amount_reported_fc'))['total'] or 0
    rapports_confirmes_date = rapports_date_qs.count()
    ecart_rapports_date = montant_rapports_date - chiffre_date
    # Écart de caisse: cash flow - dépôt - pertes financées par la caisse
    difference_date = chiffre_date - bank_deposit_amount_date - pertes_date_caisse

    single_day_activity_entries = []

    def _append_day_activity(kind, label, title, timestamp, *, summary="", amount=None, status="", actor="", anchor=""):
        single_day_activity_entries.append(
            {
                "kind": kind,
                "label": label,
                "title": title,
                "timestamp": timestamp,
                "summary": summary,
                "has_amount": amount is not None,
                "amount": _to_decimal_amount(amount) if amount is not None else Decimal("0"),
                "status": status,
                "actor": actor,
                "anchor": anchor,
            }
        )

    for lavage in lavages_date:
        wash_summary_parts = [lavage.get_type_service_display()]
        if lavage.plaque:
            wash_summary_parts.append(f"Plaque {lavage.plaque}")
        elif lavage.plaque_photo:
            wash_summary_parts.append("Photo de plaque enregistrée")
        photo_count = lavage.photos.count()
        if photo_count:
            wash_summary_parts.append(f"{photo_count} photo{'s' if photo_count > 1 else ''}")
        if lavage.notes:
            wash_summary_parts.append(lavage.notes)
        actor_name = lavage.employe.get_full_name() or lavage.employe.username
        _append_day_activity(
            "wash",
            "Lavage",
            actor_name,
            lavage.created_at,
            summary=" • ".join(wash_summary_parts),
            amount=lavage.montant,
            status="Auto" if lavage.is_system_generated else "",
            actor=actor_name,
            anchor="#single-day-washes",
        )

    for report in reports_date:
        actor_name = report.employe.get_full_name() or report.employe.username
        report_summary_parts = [f"{report.total_lavages_reported} lavage(s) déclarés"]
        if report.daily_expense_items:
            report_summary_parts.append(report.daily_expense_summary)
        if report.report_notes:
            report_summary_parts.append(report.report_notes)
        _append_day_activity(
            "report",
            "Rapport final",
            f"Rapport de {actor_name}",
            report.updated_at,
            summary=" • ".join(report_summary_parts),
            amount=report.total_amount_reported_fc,
            status="Confirmé",
            actor=actor_name,
            anchor="#single-day-reports",
        )

    if bank_deposit_date:
        deposit_actor = ""
        if bank_deposit_date.created_by:
            deposit_actor = bank_deposit_date.created_by.get_full_name() or bank_deposit_date.created_by.username
        _append_day_activity(
            "deposit",
            "Dépôt",
            "Dépôt bancaire enregistré",
            bank_deposit_date.created_at,
            summary=bank_deposit_date.notes or "Aucune note ajoutée pour ce dépôt.",
            amount=bank_deposit_date.amount,
            actor=deposit_actor,
            anchor="#single-day-deposit-trace",
        )

    for loss in losses_date_qs:
        loss_actor = (loss.created_by.get_full_name() or loss.created_by.username) if loss.created_by else ""
        loss_summary_parts = [loss.get_category_display(), loss.get_funding_source_display()]
        if loss.description:
            loss_summary_parts.append(loss.description)
        _append_day_activity(
            "loss",
            "Perte",
            loss.title,
            loss.created_at,
            summary=" • ".join(loss_summary_parts),
            amount=loss.amount,
            status="Auto" if loss.is_system_generated else "",
            actor=loss_actor,
            anchor="#single-day-losses",
        )

    for purchase in water_purchases_date:
        purchase_actor = (purchase.created_by.get_full_name() or purchase.created_by.username) if purchase.created_by else ""
        water_summary_parts = [
            purchase.supplier.name if purchase.supplier_id else "Fournisseur non renseigné",
            f"Mois {purchase.billing_month.strftime('%m/%Y')}",
        ]
        if purchase.notes:
            water_summary_parts.append(purchase.notes)
        _append_day_activity(
            "water",
            "Eau",
            "Achat d'eau",
            purchase.created_at,
            summary=" • ".join(water_summary_parts),
            amount=purchase.amount_fc,
            actor=purchase_actor,
            anchor="#single-day-water",
        )

    for purchase in fuel_purchases_date:
        purchase_actor = (purchase.created_by.get_full_name() or purchase.created_by.username) if purchase.created_by else ""
        fuel_summary_parts = [f"Mois {purchase.billing_month.strftime('%m/%Y')}"]
        if purchase.amount_fc is not None:
            fuel_summary_parts.append(f"Montant {_format_fc_compact(purchase.amount_fc)} FC")
        if purchase.notes:
            fuel_summary_parts.append(purchase.notes)
        _append_day_activity(
            "fuel",
            "Carburant",
            "Achat de carburant",
            purchase.created_at,
            summary=" • ".join(fuel_summary_parts),
            amount=purchase.amount_fc,
            actor=purchase_actor,
            anchor="#single-day-fuel",
        )

    for journal_entry in journal_entries_date:
        journal_actor = (journal_entry.created_by.get_full_name() or journal_entry.created_by.username) if journal_entry.created_by else ""
        journal_summary_parts = [journal_entry.get_category_display()]
        if journal_entry.description:
            journal_summary_parts.append(journal_entry.description)
        _append_day_activity(
            "journal",
            "Journal",
            journal_entry.title,
            journal_entry.created_at,
            summary=" • ".join(journal_summary_parts),
            amount=journal_entry.amount_fc,
            actor=journal_actor,
            anchor="#single-day-journal-entries",
        )

    for probleme in problemes_date:
        problem_actor = probleme.employe.get_full_name() or probleme.employe.username
        _append_day_activity(
            "problem",
            "Problème",
            probleme.get_categorie_display(),
            probleme.created_at,
            summary=probleme.description,
            status=probleme.get_statut_display(),
            actor=problem_actor,
            anchor="#single-day-problems",
        )

    for item in pointages_with_duration:
        pointage = item['pointage']
        if not pointage:
            continue
        pointage_actor = pointage.employe.get_full_name() or pointage.employe.username
        pointage_summary_parts = []
        if pointage.clock_in_time:
            pointage_summary_parts.append(
                f"Entrée {timezone.localtime(pointage.clock_in_time).strftime('%H:%M')}"
            )
        if pointage.clock_out_time:
            pointage_summary_parts.append(
                f"Sortie {timezone.localtime(pointage.clock_out_time).strftime('%H:%M')}"
            )
        else:
            pointage_summary_parts.append("Toujours en service")
        if item['duration']:
            pointage_summary_parts.append(f"Durée {item['duration']}")
        if pointage.daily_report_confirmed:
            pointage_summary_parts.append("Rapport final envoyé")
        _append_day_activity(
            "attendance",
            "Présence",
            pointage_actor,
            pointage.clock_in_time or pointage.updated_at or pointage.created_at,
            summary=" • ".join(pointage_summary_parts),
            status="Clôturé" if pointage.clock_out_time else "En cours",
            actor=pointage_actor,
            anchor="#single-day-attendance",
        )

    single_day_activity_entries.sort(
        key=lambda entry: entry['timestamp'] or timezone.make_aware(datetime.combine(detail_date, datetime.min.time())),
        reverse=True,
    )

    # Cash flow d'aujourd'hui (pour comparaison)
    chiffre_jour = CarWash.objects.filter(site=site, date=today).aggregate(total=Sum('montant'))['total'] or 0
    rapports_today_qs = ShiftDay.objects.filter(site=site, date=today, daily_report_confirmed=True)
    montant_rapports_today = rapports_today_qs.aggregate(total=Sum('total_amount_reported_fc'))['total'] or 0
    rapports_confirmes_today = rapports_today_qs.count()
    ecart_rapports_today = montant_rapports_today - chiffre_jour
    bank_deposit_today = DailyBankDeposit.objects.filter(site=site, date=today).first()
    bank_deposit_amount_today = bank_deposit_today.amount if bank_deposit_today else 0

    losses_today_qs = SiteLossEntry.objects.filter(site=site, date=today)
    pertes_today_total = losses_today_qs.aggregate(total=Sum('amount'))['total'] or 0
    pertes_today_caisse = losses_today_qs.filter(funding_source='CAISSE').aggregate(total=Sum('amount'))['total'] or 0
    pertes_today_banque = losses_today_qs.filter(funding_source='BANQUE').aggregate(total=Sum('amount'))['total'] or 0
    difference_today = chiffre_jour - bank_deposit_amount_today - pertes_today_caisse

    # Résumé hebdomadaire (lundi -> dimanche)
    week_start = detail_date - timedelta(days=detail_date.weekday())
    week_end = week_start + timedelta(days=6)
    week_range_label = f"{week_start.strftime('%d/%m/%Y')} - {week_end.strftime('%d/%m/%Y')}"

    chiffre_week = CarWash.objects.filter(
        site=site,
        date__gte=week_start,
        date__lte=week_end,
    ).aggregate(total=Sum('montant'))['total'] or 0
    rapports_week_qs = ShiftDay.objects.filter(
        site=site,
        date__gte=week_start,
        date__lte=week_end,
        daily_report_confirmed=True,
    )
    montant_rapports_week = rapports_week_qs.aggregate(total=Sum('total_amount_reported_fc'))['total'] or 0
    rapports_confirmes_week = rapports_week_qs.count()
    ecart_rapports_week = montant_rapports_week - chiffre_week

    bank_deposit_week = DailyBankDeposit.objects.filter(
        site=site,
        date__gte=week_start,
        date__lte=week_end,
    ).aggregate(total=Sum('amount'))['total'] or 0

    losses_week_qs = SiteLossEntry.objects.filter(
        site=site,
        date__gte=week_start,
        date__lte=week_end,
    )
    pertes_week_total = losses_week_qs.aggregate(total=Sum('amount'))['total'] or 0
    pertes_week_caisse = losses_week_qs.filter(funding_source='CAISSE').aggregate(total=Sum('amount'))['total'] or 0
    pertes_week_banque = losses_week_qs.filter(funding_source='BANQUE').aggregate(total=Sum('amount'))['total'] or 0
    bank_net_week = bank_deposit_week - pertes_week_banque
    caisse_balance_week = chiffre_week - bank_deposit_week - pertes_week_caisse

    comparison_periods = _build_site_comparison_periods(site, detail_date, selected_scope="week")

    previous_week_start = week_start - timedelta(days=7)
    previous_week_end = previous_week_start + timedelta(days=6)
    next_week_start = week_start + timedelta(days=7)
    next_week_end = next_week_start + timedelta(days=6)
    can_view_next_week = next_week_start <= today

    show_period_breakdown = bool(
        selected_date_start and selected_date_end and selected_date_start < selected_date_end
    )

    period_bank_deposits = []
    period_bank_deposit_total = Decimal("0")
    period_losses = []
    period_losses_total = Decimal("0")
    period_losses_caisse = Decimal("0")
    period_losses_banque = Decimal("0")
    period_bank_net = Decimal("0")
    period_caisse_balance = Decimal("0")
    period_reports = []
    period_reported_total = Decimal("0")
    period_reports_count = 0
    period_report_variance = Decimal("0")
    period_water_purchases = []
    period_water_total = Decimal("0")
    period_water_count = 0
    period_fuel_purchases = []
    period_fuel_count = 0
    period_journal_entries = []
    period_journal_amount_total = Decimal("0")
    period_journal_count = 0
    period_problems = []
    period_problem_count = 0
    period_presence_count = 0
    period_distinct_employees = 0
    period_daily_rows = []

    if show_period_breakdown:
        period_bank_deposits_qs = DailyBankDeposit.objects.filter(
            site=site,
            date__gte=selected_date_start,
            date__lte=selected_date_end,
        ).select_related("created_by").order_by("-date", "-created_at")
        period_losses_qs = SiteLossEntry.objects.filter(
            site=site,
            date__gte=selected_date_start,
            date__lte=selected_date_end,
        ).select_related("created_by").order_by("-date", "-created_at")
        period_reports_qs = ShiftDay.objects.filter(
            site=site,
            date__gte=selected_date_start,
            date__lte=selected_date_end,
            daily_report_confirmed=True,
        ).select_related("employe").order_by("-date", "-updated_at")
        period_pointages_qs = ShiftDay.objects.filter(
            site=site,
            date__gte=selected_date_start,
            date__lte=selected_date_end,
            clock_in_time__isnull=False,
        ).select_related("employe").order_by("-date", "-clock_in_time")
        period_water_purchases_qs = SiteWaterPurchase.objects.filter(
            site=site,
            purchase_date__gte=selected_date_start,
            purchase_date__lte=selected_date_end,
        ).select_related("created_by", "supplier").order_by("-purchase_date", "-created_at")
        period_fuel_purchases_qs = SiteFuelPurchase.objects.filter(
            site=site,
            purchase_date__gte=selected_date_start,
            purchase_date__lte=selected_date_end,
        ).select_related("created_by").order_by("-purchase_date", "-created_at")
        period_journal_entries_qs = SiteJournalEntry.objects.filter(
            site=site,
            entry_date__gte=selected_date_start,
            entry_date__lte=selected_date_end,
        ).select_related("created_by").order_by("-entry_date", "-created_at")
        period_problems_qs = IssueReport.objects.filter(
            site=site,
            created_at__date__gte=selected_date_start,
            created_at__date__lte=selected_date_end,
        ).select_related("employe").order_by("-created_at")

        period_bank_deposits = list(period_bank_deposits_qs)
        period_losses = list(period_losses_qs)
        period_reports = list(period_reports_qs)
        period_water_purchases = list(period_water_purchases_qs)
        period_fuel_purchases = list(period_fuel_purchases_qs)
        period_journal_entries = list(period_journal_entries_qs)
        period_problems = list(period_problems_qs)

        period_bank_deposit_total = _to_decimal_amount(
            period_bank_deposits_qs.aggregate(total=Sum("amount"))["total"]
        )
        period_losses_total = _to_decimal_amount(
            period_losses_qs.aggregate(total=Sum("amount"))["total"]
        )
        period_losses_caisse = _to_decimal_amount(
            period_losses_qs.filter(funding_source="CAISSE").aggregate(total=Sum("amount"))["total"]
        )
        period_losses_banque = _to_decimal_amount(
            period_losses_qs.filter(funding_source="BANQUE").aggregate(total=Sum("amount"))["total"]
        )
        period_bank_net = period_bank_deposit_total - period_losses_banque
        period_caisse_balance = _to_decimal_amount(chiffre_periode) - period_bank_deposit_total - period_losses_caisse
        period_reported_total = _to_decimal_amount(
            period_reports_qs.aggregate(total=Sum("total_amount_reported_fc"))["total"]
        )
        period_reports_count = period_reports_qs.count()
        period_report_variance = period_reported_total - _to_decimal_amount(chiffre_periode)
        period_water_total = _to_decimal_amount(
            period_water_purchases_qs.aggregate(total=Sum("amount_fc"))["total"]
        )
        period_water_count = period_water_purchases_qs.count()
        period_fuel_count = period_fuel_purchases_qs.count()
        period_journal_amount_total = _to_decimal_amount(
            period_journal_entries_qs.aggregate(total=Sum("amount_fc"))["total"]
        )
        period_journal_count = period_journal_entries_qs.count()
        period_problem_count = period_problems_qs.count()
        period_presence_count = period_pointages_qs.count()
        period_distinct_employees = period_pointages_qs.values("employe_id").distinct().count()

        cash_by_day = {
            row["date"]: {
                "cash_flow": _to_decimal_amount(row["cash_flow"]),
                "lavages_count": row["lavages_count"] or 0,
            }
            for row in CarWash.objects.filter(
                site=site,
                date__gte=selected_date_start,
                date__lte=selected_date_end,
            ).values("date").annotate(
                cash_flow=Sum("montant"),
                lavages_count=Count("id"),
            )
        }
        reports_by_day = {
            row["date"]: {
                "reported_cash": _to_decimal_amount(row["reported_cash"]),
                "reports_count": row["reports_count"] or 0,
            }
            for row in ShiftDay.objects.filter(
                site=site,
                date__gte=selected_date_start,
                date__lte=selected_date_end,
                daily_report_confirmed=True,
            ).values("date").annotate(
                reported_cash=Sum("total_amount_reported_fc"),
                reports_count=Count("id"),
            )
        }
        deposits_by_day = {deposit.date: deposit for deposit in period_bank_deposits}
        losses_by_day = {
            row["date"]: {
                "pertes_total": _to_decimal_amount(row["pertes_total"]),
                "pertes_caisse": _to_decimal_amount(row["pertes_caisse"]),
                "pertes_banque": _to_decimal_amount(row["pertes_banque"]),
                "losses_count": row["losses_count"] or 0,
            }
            for row in SiteLossEntry.objects.filter(
                site=site,
                date__gte=selected_date_start,
                date__lte=selected_date_end,
            ).values("date").annotate(
                pertes_total=Sum("amount"),
                pertes_caisse=Sum("amount", filter=Q(funding_source="CAISSE")),
                pertes_banque=Sum("amount", filter=Q(funding_source="BANQUE")),
                losses_count=Count("id"),
            )
        }
        problems_by_day = {
            row["created_at__date"]: row["problem_count"] or 0
            for row in period_problems_qs.values("created_at__date").annotate(problem_count=Count("id"))
        }
        water_by_day = {
            row["purchase_date"]: {
                "water_count": row["water_count"] or 0,
                "water_total": _to_decimal_amount(row["water_total"]),
            }
            for row in period_water_purchases_qs.values("purchase_date").annotate(
                water_count=Count("id"),
                water_total=Sum("amount_fc"),
            )
        }
        journal_by_day = {
            row["entry_date"]: {
                "journal_count": row["journal_count"] or 0,
                "journal_amount": _to_decimal_amount(row["journal_amount"]),
            }
            for row in period_journal_entries_qs.values("entry_date").annotate(
                journal_count=Count("id"),
                journal_amount=Sum("amount_fc"),
            )
        }

        cursor = selected_date_start
        while cursor <= selected_date_end:
            day_cash = cash_by_day.get(cursor, {})
            day_reports = reports_by_day.get(cursor, {})
            day_deposit = deposits_by_day.get(cursor)
            day_losses = losses_by_day.get(cursor, {})
            day_water = water_by_day.get(cursor, {})
            day_journal = journal_by_day.get(cursor, {})

            cash_flow_day = _to_decimal_amount(day_cash.get("cash_flow"))
            bank_deposit_day = _to_decimal_amount(day_deposit.amount if day_deposit else 0)
            pertes_caisse_day = _to_decimal_amount(day_losses.get("pertes_caisse"))
            pertes_banque_day = _to_decimal_amount(day_losses.get("pertes_banque"))
            pertes_total_day = _to_decimal_amount(day_losses.get("pertes_total"))

            period_daily_rows.append(
                {
                    "date": cursor,
                    "cash_flow": cash_flow_day,
                    "lavages_count": day_cash.get("lavages_count", 0),
                    "reported_cash": _to_decimal_amount(day_reports.get("reported_cash")),
                    "reports_count": day_reports.get("reports_count", 0),
                    "bank_deposit": bank_deposit_day,
                    "bank_net": bank_deposit_day - pertes_banque_day,
                    "pertes_total": pertes_total_day,
                    "pertes_caisse": pertes_caisse_day,
                    "pertes_banque": pertes_banque_day,
                    "ecart_caisse": cash_flow_day - bank_deposit_day - pertes_caisse_day,
                    "problems_count": problems_by_day.get(cursor, 0),
                    "water_count": day_water.get("water_count", 0),
                    "journal_count": day_journal.get("journal_count", 0),
                    "detail_query": f"date_debut={cursor.strftime('%Y-%m-%d')}&date_fin={cursor.strftime('%Y-%m-%d')}",
                }
            )
            cursor += timedelta(days=1)
    
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
        'montant_rapports_date': montant_rapports_date,
        'rapports_confirmes_date': rapports_confirmes_date,
        'ecart_rapports_date': ecart_rapports_date,
        'montant_rapports_today': montant_rapports_today,
        'rapports_confirmes_today': rapports_confirmes_today,
        'ecart_rapports_today': ecart_rapports_today,
        'bank_deposit_date': bank_deposit_date,
        'bank_deposit_amount_date': bank_deposit_amount_date,
        'bank_deposit_today': bank_deposit_today,
        'bank_deposit_amount_today': bank_deposit_amount_today,
        'losses_date': losses_date_qs,
        'pertes_date_total': pertes_date_total,
        'pertes_date_caisse': pertes_date_caisse,
        'pertes_date_banque': pertes_date_banque,
        'pertes_today_total': pertes_today_total,
        'pertes_today_caisse': pertes_today_caisse,
        'pertes_today_banque': pertes_today_banque,
        'difference_date': difference_date,
        'difference_today': difference_today,
        'week_start': week_start,
        'week_end': week_end,
        'week_range_label': week_range_label,
        'selected_week_anchor': selected_week_anchor,
        'chiffre_week': chiffre_week,
        'montant_rapports_week': montant_rapports_week,
        'rapports_confirmes_week': rapports_confirmes_week,
        'ecart_rapports_week': ecart_rapports_week,
        'bank_deposit_week': bank_deposit_week,
        'bank_net_week': bank_net_week,
        'pertes_week_total': pertes_week_total,
        'pertes_week_caisse': pertes_week_caisse,
        'pertes_week_banque': pertes_week_banque,
        'caisse_balance_week': caisse_balance_week,
        'comparison_periods': comparison_periods,
        'previous_week_start': previous_week_start,
        'previous_week_end': previous_week_end,
        'next_week_start': next_week_start,
        'next_week_end': next_week_end,
        'can_view_next_week': can_view_next_week,
        'show_period_breakdown': show_period_breakdown,
        'period_bank_deposits': period_bank_deposits,
        'period_bank_deposit_total': period_bank_deposit_total,
        'period_losses': period_losses,
        'period_losses_total': period_losses_total,
        'period_losses_caisse': period_losses_caisse,
        'period_losses_banque': period_losses_banque,
        'period_bank_net': period_bank_net,
        'period_caisse_balance': period_caisse_balance,
        'period_reports': period_reports,
        'period_reported_total': period_reported_total,
        'period_reports_count': period_reports_count,
        'period_report_variance': period_report_variance,
        'period_water_purchases': period_water_purchases,
        'period_water_total': period_water_total,
        'period_water_count': period_water_count,
        'period_fuel_purchases': period_fuel_purchases,
        'period_fuel_count': period_fuel_count,
        'period_journal_entries': period_journal_entries,
        'period_journal_amount_total': period_journal_amount_total,
        'period_journal_count': period_journal_count,
        'period_problems': period_problems,
        'period_problem_count': period_problem_count,
        'period_presence_count': period_presence_count,
        'period_distinct_employees': period_distinct_employees,
        'period_daily_rows': period_daily_rows,
        'lavages_date': lavages_date,
        'reports_date': reports_date,
        'water_purchases_date': water_purchases_date,
        'fuel_purchases_date': fuel_purchases_date,
        'journal_entries_date': journal_entries_date,
        'single_day_activity_entries': single_day_activity_entries,
        'photos_lavages': photos_lavages,
        'photos_lavages_total': photos_lavages_total,
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
    
    recent_journal_entries = list(
        SiteJournalEntry.objects.filter(site=site)
        .select_related("created_by")
        .order_by("-entry_date", "-created_at")[:4]
    )
    journal_entries_count = SiteJournalEntry.objects.filter(site=site).count()

    # Ajouter les statistiques des documents
    documents_count = SiteDocument.objects.filter(site=site).count()
    context['documents_count'] = documents_count
    context['recent_journal_entries'] = recent_journal_entries
    context['journal_entries_count'] = journal_entries_count
    
    return render(request, 'admin/site_detail.html', context)


@login_required
@no_cache_view
def admin_site_history_comparison(request, site_id):
    """
    Page dédiée au comparatif historique du site.
    Affiche une lecture claire entre semaines, mois et années.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    today = timezone.localdate()
    detail_date = today
    date_param = request.GET.get("date")
    if date_param:
        try:
            detail_date = datetime.strptime(date_param, "%Y-%m-%d").date()
        except ValueError:
            detail_date = today

    current_scope = request.GET.get("scope", "week")
    if current_scope not in {"week", "month", "year"}:
        current_scope = "week"

    comparison_periods = _build_site_comparison_periods(site, detail_date, selected_scope=current_scope)
    selected_period = next(
        (period for period in comparison_periods if period["key"] == current_scope),
        comparison_periods[0] if comparison_periods else None,
    )
    monthly_rankings_period = next(
        (period for period in comparison_periods if period["key"] == "month"),
        None,
    )
    next_month_forecast = _build_next_month_forecast(detail_date, comparison_periods)

    scope_snapshots = []
    for period in comparison_periods:
        current_item = period.get("current_item")
        scope_snapshots.append(
            {
                "key": period["key"],
                "label": period["toggle_label"],
                "anchor_label": current_item["label"] if current_item else "Aucune donnée",
                "cash_flow": current_item["cash_flow"] if current_item else 0,
                "bank_net": current_item["bank_net"] if current_item else 0,
                "pertes_total": current_item["pertes_total"] if current_item else 0,
                "url": (
                    f"{reverse('admin_site_history_comparison', kwargs={'site_id': site.id})}"
                    f"?scope={period['key']}&date={detail_date.strftime('%Y-%m-%d')}"
                ),
                "is_active": period["key"] == current_scope,
            }
        )

    context = {
        "site": site,
        "today": today,
        "detail_date": detail_date,
        "current_scope": current_scope,
        "comparison_periods": comparison_periods,
        "selected_period": selected_period,
        "monthly_rankings_period": monthly_rankings_period,
        "scope_snapshots": scope_snapshots,
        "next_month_forecast": next_month_forecast,
    }
    return render(request, "admin/site_history_comparison.html", context)


@login_required
@no_cache_view
def admin_site_journal(request, site_id):
    ensure_superuser_admin_profile(request.user)
    if not is_admin_user(request.user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    selected_month = _parse_month_filter(request.GET.get("month"))
    entries = list(
        SiteJournalEntry.objects.filter(site=site)
        .select_related("created_by")
        .order_by("-entry_date", "-created_at")
    )
    journal_overview = _build_site_journal_overview(entries, selected_month)

    if request.method == "POST":
        form = SiteJournalEntryForm(request.POST, reminder_user=request.user)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.site = site
            entry.created_by = request.user
            entry.save()
            messages.success(request, "L'entrée du journal a été enregistrée.")
            month_query = entry.entry_date.replace(day=1).strftime("%Y-%m")
            return redirect(f"{reverse('admin_site_journal', kwargs={'site_id': site.id})}?month={month_query}")
    else:
        form = SiteJournalEntryForm(
            initial={"entry_date": timezone.localdate()},
            reminder_user=request.user,
        )

    return render(
        request,
        "admin/site_journal.html",
        {
            "site": site,
            "form": form,
            "selected_month": selected_month,
            "selected_month_input": selected_month.strftime("%Y-%m"),
            "month_summaries": journal_overview["month_summaries"],
            "selected_month_data": journal_overview["selected_month_data"],
        },
    )


@login_required
@no_cache_view
def admin_edit_site_journal_entry(request, site_id, entry_id):
    ensure_superuser_admin_profile(request.user)
    if not is_admin_user(request.user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    entry = get_object_or_404(SiteJournalEntry, id=entry_id, site=site)
    month_query = request.GET.get("month") or entry.entry_date.replace(day=1).strftime("%Y-%m")

    if request.method == "POST":
        form = SiteJournalEntryForm(request.POST, instance=entry, reminder_user=request.user)
        if form.is_valid():
            updated_entry = form.save()
            messages.success(request, "L'entrée du journal a été mise à jour.")
            month_query = updated_entry.entry_date.replace(day=1).strftime("%Y-%m")
            return redirect(f"{reverse('admin_site_journal', kwargs={'site_id': site.id})}?month={month_query}")
    else:
        form = SiteJournalEntryForm(instance=entry, reminder_user=request.user)

    return render(
        request,
        "admin/edit_site_journal_entry.html",
        {
            "site": site,
            "entry": entry,
            "form": form,
            "month_query": month_query,
        },
    )


@login_required
@no_cache_view
def admin_move_site_journal_entry(request, site_id, entry_id):
    ensure_superuser_admin_profile(request.user)
    if not is_admin_user(request.user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    entry = get_object_or_404(SiteJournalEntry, id=entry_id, site=site)
    month_query = request.GET.get("month") or entry.entry_date.replace(day=1).strftime("%Y-%m")

    if request.method == "POST":
        form = SiteJournalEntryMoveForm(request.POST, entry_instance=entry)
        if form.is_valid():
            previous_date = entry.entry_date
            previous_category = entry.category
            moved_entry = form.save(entry)
            destination_month = moved_entry.entry_date.replace(day=1).strftime("%Y-%m")
            destination_anchor = f"journal-category-{moved_entry.category.lower()}"

            AuditLog.log(
                user=request.user,
                action="MODIFIER",
                description=f"Entrée du journal migrée pour {site.nom}: {moved_entry.title}",
                content_object=moved_entry,
                donnees_avant={
                    "entry_date": previous_date.strftime("%Y-%m-%d"),
                    "category": previous_category,
                },
                donnees_apres={
                    "entry_date": moved_entry.entry_date.strftime("%Y-%m-%d"),
                    "category": moved_entry.category,
                },
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            messages.success(request, "L'entrée du journal a été migrée vers la nouvelle catégorie/date.")
            return redirect(
                f"{reverse('admin_site_journal', kwargs={'site_id': site.id})}?month={destination_month}#{destination_anchor}"
            )
    else:
        form = SiteJournalEntryMoveForm(entry_instance=entry)

    return render(
        request,
        "admin/move_site_journal_entry.html",
        {
            "site": site,
            "entry": entry,
            "form": form,
            "month_query": month_query,
        },
    )


@login_required
@no_cache_view
def admin_delete_site_journal_entry(request, site_id, entry_id):
    ensure_superuser_admin_profile(request.user)
    if not is_admin_user(request.user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    entry = get_object_or_404(SiteJournalEntry, id=entry_id, site=site)
    month_query = request.GET.get("month") or entry.entry_date.replace(day=1).strftime("%Y-%m")

    if request.method == "POST":
        redirect_month = entry.entry_date.replace(day=1).strftime("%Y-%m")
        entry.delete()
        messages.success(request, "L'entrée du journal a été supprimée.")
        return redirect(f"{reverse('admin_site_journal', kwargs={'site_id': site.id})}?month={redirect_month}")

    return render(
        request,
        "admin/delete_site_journal_entry.html",
        {
            "site": site,
            "entry": entry,
            "month_query": month_query,
        },
    )


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
            # Correction admin explicite: ce total doit modifier le cash flow
            # réel sans être neutralisé par le rapport final déjà soumis.
            messages.success(request, f'Montant total de {montant_decimal:,.0f} FC ajouté avec succès pour le {date_obj.strftime("%d/%m/%Y")} !')
            return _redirect_to_admin_site_detail(request, site, date_obj=date_obj)
            
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
    next_url = _safe_next_url(request) or ''
    
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
                    'next_url': next_url,
                })
            
            if not date_wash:
                messages.error(request, 'La date est requise.')
                return render(request, 'admin/add_wash.html', {
                    'site': site,
                    'employes_site': employes_site,
                    'types_service': CarWash.TYPE_SERVICE_CHOICES,
                    'next_url': next_url,
                })
            
            if not type_service:
                messages.error(request, 'Le type de service est requis.')
                return render(request, 'admin/add_wash.html', {
                    'site': site,
                    'employes_site': employes_site,
                    'types_service': CarWash.TYPE_SERVICE_CHOICES,
                    'next_url': next_url,
                })
            
            if not montant:
                messages.error(request, 'Le montant est requis.')
                return render(request, 'admin/add_wash.html', {
                    'site': site,
                    'employes_site': employes_site,
                    'types_service': CarWash.TYPE_SERVICE_CHOICES,
                    'next_url': next_url,
                })
            
            photos = request.FILES.getlist('photos')
            
            # Récupérer l'employé
            employe = get_object_or_404(User, id=employe_id)
            
            # Vérifier que l'employé appartient au site
            if not hasattr(employe, 'userprofile') or employe.userprofile.site != site:
                messages.error(request, 'L\'employé sélectionné n\'appartient pas à ce site.')
                return render(request, 'admin/add_wash.html', {
                    'site': site,
                    'employes_site': employes_site,
                    'types_service': CarWash.TYPE_SERVICE_CHOICES,
                    'next_url': next_url,
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
                    'next_url': next_url,
                })
            
            # Créer le lavage
            lavage = CarWash.objects.create(
                employe=employe,
                site=site,
                date=date_obj,
                type_service=type_service,
                plaque=plaque,
                montant=montant,
                notes=notes,
                # Les lavages oubliés saisis par l'admin doivent rester
                # additifs dans le cash flow même si un rapport final existe déjà.
                system_source=ADMIN_CORRECTION_SOURCE,
            )
            
            # Traiter les photos si présentes (toutes marquées comme "après lavage")
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
            # Correction admin explicite: le lavage ajouté doit augmenter le
            # cash flow au lieu de réduire l'ajustement automatique du rapport.
            messages.success(request, f'Lavage enregistré avec succès pour le {date_obj.strftime("%d/%m/%Y")} !')
            return _redirect_to_admin_site_detail(request, site, date_obj=date_obj)
            
        except Exception as e:
            messages.error(request, f'Erreur lors de l\'enregistrement: {str(e)}')
    
    # GET request - afficher le formulaire
    today = timezone.localdate()
    date_param = request.GET.get('date')
    if date_param:
        try:
            today = datetime.strptime(date_param, '%Y-%m-%d').date()
        except ValueError:
            pass
    return render(request, 'admin/add_wash.html', {
        'site': site,
        'employes_site': employes_site,
        'types_service': CarWash.TYPE_SERVICE_CHOICES,
        'today': today,
        'next_url': next_url,
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
            original_date = lavage.date

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
            # Les corrections admin doivent conserver leur impact financier
            # direct et ne pas être rebalancées automatiquement par le rapport.

            if added_photos:
                messages.success(request, f"Lavage modifié avec succès. {added_photos} photo(s) ajoutée(s).")
            else:
                messages.success(request, "Lavage modifié avec succès.")
            return _redirect_to_admin_site_detail(request, site, date_obj=date_obj)
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
        # Une suppression admin doit diminuer le cash flow directement.
        messages.success(request, "Lavage supprimé avec succès.")
        return _redirect_to_admin_site_detail(request, site, date_obj=lavage.date)

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
    expense_form = _build_initial_daily_expense_form(pointage)
    submitted_total_amount = f"{pointage.total_amount_reported_fc:.2f}"

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
                'total_amount_reported_fc': str(pointage.total_amount_reported_fc),
                'daily_expenses_total_fc': str(pointage.daily_expenses_total_fc),
                'daily_expenses': pointage.daily_expenses,
            }

            new_clock_in = request.POST.get('clock_in_time', '').strip()
            new_clock_out = request.POST.get('clock_out_time', '').strip()
            clear_clock_out = request.POST.get('clear_clock_out') == 'on'
            total_lavages_reported = request.POST.get('total_lavages_reported', '').strip()
            submitted_total_amount = request.POST.get('total_amount_reported_fc', '').strip()
            expense_form = _parse_daily_expenses_form(request.POST)
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

            if pointage.daily_report_confirmed:
                try:
                    total_amount_reported = Decimal(submitted_total_amount or '0')
                except (ArithmeticError, InvalidOperation, ValueError):
                    raise ValueError("Le montant final déclaré est invalide.")
                if total_amount_reported < 0:
                    raise ValueError("Le montant final déclaré ne peut pas être négatif.")
                if expense_form['errors']:
                    raise ValueError(expense_form['errors'][0])

                pointage.total_amount_reported_fc = total_amount_reported
                pointage.daily_expenses = expense_form['items']
                pointage.daily_expenses_total_fc = expense_form['total']
            else:
                pointage.total_amount_reported_fc = Decimal('0')
                pointage.daily_expenses = []
                pointage.daily_expenses_total_fc = Decimal('0')

            if pointage.clock_in_time and pointage.clock_out_time and pointage.clock_out_time < pointage.clock_in_time:
                messages.error(request, "L'heure de sortie ne peut pas être avant l'heure d'entrée.")
                return redirect('admin_edit_pointage', site_id=site.id, pointage_id=pointage.id)

            pointage.corrected_by = user
            pointage.correction_reason = motif
            pointage.corrected_at = timezone.now()
            pointage.save()
            sync_site_finance_from_daily_reports(site, pointage.date, actor=user)

            donnees_apres = {
                'clock_in_time': str(pointage.clock_in_time) if pointage.clock_in_time else None,
                'clock_out_time': str(pointage.clock_out_time) if pointage.clock_out_time else None,
                'daily_report_confirmed': pointage.daily_report_confirmed,
                'total_lavages_reported': pointage.total_lavages_reported,
                'total_amount_reported_fc': str(pointage.total_amount_reported_fc),
                'daily_expenses_total_fc': str(pointage.daily_expenses_total_fc),
                'daily_expenses': pointage.daily_expenses,
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
            return _redirect_to_admin_site_detail(request, site, date_obj=date_obj)
        except ValueError as e:
            messages.error(request, f"Erreur de validation: {str(e)}")
        except Exception as e:
            messages.error(request, f"Erreur lors de la correction du pointage: {str(e)}")

    return render(request, 'admin/edit_pointage.html', {
        'site': site,
        'pointage': pointage,
        'expense_form': expense_form,
        'submitted_total_amount': submitted_total_amount,
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
        should_sync_finance = pointage.daily_report_confirmed
        pointage_label = str(pointage)
        pointage_date = pointage.date
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
        if should_sync_finance:
            sync_site_finance_from_daily_reports(site, pointage_date, actor=user)

        messages.success(request, "Pointage supprimé avec succès.")
        return _redirect_to_admin_site_detail(request, site, date_obj=pointage_date)

    return render(request, 'admin/delete_pointage.html', {
        'site': site,
        'pointage': pointage,
        'next_url': _safe_next_url(request) or '',
    })


@login_required
@no_cache_view
def admin_delete_daily_report(request, site_id, pointage_id):
    """
    Supprime uniquement le rapport de fin de journée sans supprimer le pointage.
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
            return redirect('admin_delete_daily_report', site_id=site.id, pointage_id=pointage.id)

        donnees_avant = {
            'id': pointage.id,
            'employe': pointage.employe.username,
            'date': str(pointage.date),
            'daily_report_confirmed': pointage.daily_report_confirmed,
            'total_lavages_reported': pointage.total_lavages_reported,
            'total_amount_reported_fc': str(pointage.total_amount_reported_fc),
            'daily_expenses_total_fc': str(pointage.daily_expenses_total_fc),
            'daily_expenses': pointage.daily_expenses,
        }

        pointage.daily_report_confirmed = False
        pointage.total_lavages_reported = 0
        pointage.total_amount_reported_fc = Decimal('0')
        pointage.lavages_review = ""
        pointage.problems_review = ""
        pointage.report_notes = ""
        pointage.daily_expenses = []
        pointage.daily_expenses_total_fc = Decimal('0')
        pointage.corrected_by = user
        pointage.correction_reason = motif
        pointage.corrected_at = timezone.now()
        pointage.save()
        sync_site_finance_from_daily_reports(site, pointage.date, actor=user)

        donnees_apres = {
            'daily_report_confirmed': pointage.daily_report_confirmed,
            'total_lavages_reported': pointage.total_lavages_reported,
            'total_amount_reported_fc': str(pointage.total_amount_reported_fc),
            'daily_expenses_total_fc': str(pointage.daily_expenses_total_fc),
            'daily_expenses': pointage.daily_expenses,
        }

        AuditLog.log(
            user=user,
            action="SUPPRIMER",
            description=f"Rapport de fin de journée supprimé par admin: {pointage}",
            motif=motif,
            content_object=pointage,
            donnees_avant=donnees_avant,
            donnees_apres=donnees_apres,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        messages.success(request, "Rapport de fin de journée supprimé avec succès.")
        return _redirect_to_admin_site_detail(request, site, date_obj=pointage.date)

    return render(request, 'admin/delete_daily_report.html', {
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
    next_url = _safe_next_url(request) or ''
    
    if request.method == 'POST':
        try:
            # Récupérer les données du formulaire
            date_deposit = request.POST.get('date')
            amount = request.POST.get('amount')
            notes = request.POST.get('notes', '')
            
            # Validation des champs requis
            if not date_deposit:
                messages.error(request, 'La date est requise.')
                return _render_bank_deposit_form(request, site, today, next_url=next_url)
            
            if not amount:
                messages.error(request, 'Le montant est requis.')
                return _render_bank_deposit_form(request, site, date_deposit or today, next_url=next_url)
            
            # Convertir la date
            try:
                date_obj = datetime.strptime(date_deposit, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'Format de date invalide.')
                return _render_bank_deposit_form(request, site, date_deposit or today, next_url=next_url)
            
            # Vérifier le montant
            try:
                amount_decimal = float(amount)
                if amount_decimal < 0:
                        messages.error(request, 'Le montant ne peut pas être négatif.')
                        return _render_bank_deposit_form(request, site, date_obj, next_url=next_url)
            except ValueError:
                messages.error(request, 'Montant invalide.')
                return _render_bank_deposit_form(request, site, date_deposit or today, next_url=next_url)
            
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
            return _redirect_to_admin_site_detail(request, site, date_obj=date_obj)
            
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
    
    return _render_bank_deposit_form(request, site, today, deposit=deposit, next_url=next_url)


@login_required
@no_cache_view
def admin_delete_bank_deposit(request, site_id, deposit_id):
    """
    Supprimer un dépôt bancaire existant.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    deposit = get_object_or_404(DailyBankDeposit, id=deposit_id, site=site)

    if request.method == 'POST':
        motif = request.POST.get('motif', '').strip()
        if not motif:
            messages.error(request, "Le motif de suppression est obligatoire.")
            return redirect('admin_delete_bank_deposit', site_id=site.id, deposit_id=deposit.id)

        donnees_avant = {
            'date': str(deposit.date),
            'amount': str(deposit.amount),
            'notes': deposit.notes,
        }
        deposit_date = deposit.date
        amount = deposit.amount
        deposit.delete()

        AuditLog.log(
            user=user,
            action="SUPPRIMER",
            description=f"Dépôt bancaire supprimé sur {site.nom}: {amount} FC ({deposit_date})",
            motif=motif,
            donnees_avant=donnees_avant,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        messages.success(request, "Dépôt bancaire supprimé avec succès.")
        return _redirect_to_admin_site_detail(request, site, date_obj=deposit_date)

    return render(request, 'admin/delete_bank_deposit.html', {
        'site': site,
        'deposit': deposit,
        'next_url': _safe_next_url(request) or '',
    })


@login_required
@no_cache_view
def admin_site_losses(request, site_id):
    """
    Gestion financière et centre de correction: cash flow, dépôts banque,
    pertes et pointages, en vue jour ou semaine.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    today = timezone.localdate()
    selected_date = today
    period = request.GET.get('period', 'day')
    metric = request.GET.get('metric', 'losses')

    if period not in {'day', 'week'}:
        period = 'day'
    if metric not in {'cashflow', 'bank', 'losses', 'pointages'}:
        metric = 'losses'

    date_param = request.GET.get('date')
    if date_param:
        try:
            selected_date = datetime.strptime(date_param, '%Y-%m-%d').date()
        except ValueError:
            messages.warning(request, "Date invalide. La date du jour a été utilisée.")

    week_start = selected_date - timedelta(days=selected_date.weekday())
    week_end = week_start + timedelta(days=6)
    week_range_label = f"{week_start.strftime('%d/%m/%Y')} - {week_end.strftime('%d/%m/%Y')}"

    losses_day_qs = SiteLossEntry.objects.filter(site=site, date=selected_date).select_related('created_by').order_by('-created_at')
    pertes_total = losses_day_qs.aggregate(total=Sum('amount'))['total'] or 0
    pertes_caisse = losses_day_qs.filter(funding_source='CAISSE').aggregate(total=Sum('amount'))['total'] or 0
    pertes_banque = losses_day_qs.filter(funding_source='BANQUE').aggregate(total=Sum('amount'))['total'] or 0

    cash_flow_date = CarWash.objects.filter(site=site, date=selected_date).aggregate(total=Sum('montant'))['total'] or 0
    bank_deposit_date = DailyBankDeposit.objects.filter(site=site, date=selected_date).aggregate(total=Sum('amount'))['total'] or 0
    ecart_caisse_date = cash_flow_date - bank_deposit_date - pertes_caisse

    cash_flow_week = CarWash.objects.filter(
        site=site,
        date__gte=week_start,
        date__lte=week_end,
    ).aggregate(total=Sum('montant'))['total'] or 0

    bank_deposit_week = DailyBankDeposit.objects.filter(
        site=site,
        date__gte=week_start,
        date__lte=week_end,
    ).aggregate(total=Sum('amount'))['total'] or 0

    losses_week_qs = SiteLossEntry.objects.filter(
        site=site,
        date__gte=week_start,
        date__lte=week_end,
    )
    pertes_week_total = losses_week_qs.aggregate(total=Sum('amount'))['total'] or 0
    pertes_week_caisse = losses_week_qs.filter(funding_source='CAISSE').aggregate(total=Sum('amount'))['total'] or 0
    pertes_week_banque = losses_week_qs.filter(funding_source='BANQUE').aggregate(total=Sum('amount'))['total'] or 0
    bank_net_week = bank_deposit_week - pertes_week_banque
    caisse_balance_week = cash_flow_week - bank_deposit_week - pertes_week_caisse

    if period == 'week':
        range_start = week_start
        range_end = week_end
        range_label = f"Semaine du {week_range_label}"
    else:
        range_start = selected_date
        range_end = selected_date
        range_label = f"Journée du {selected_date.strftime('%d/%m/%Y')}"

    cashflow_entries = CarWash.objects.filter(
        site=site,
        date__gte=range_start,
        date__lte=range_end,
    ).select_related('employe').prefetch_related('photos').order_by('-date', '-created_at')

    bank_entries = DailyBankDeposit.objects.filter(
        site=site,
        date__gte=range_start,
        date__lte=range_end,
    ).select_related('created_by').order_by('-date', '-created_at')

    loss_entries = SiteLossEntry.objects.filter(
        site=site,
        date__gte=range_start,
        date__lte=range_end,
    ).select_related('created_by').order_by('-date', '-created_at')

    pointage_entries = ShiftDay.objects.filter(
        site=site,
        date__gte=range_start,
        date__lte=range_end,
    ).select_related('employe').order_by('-date', '-clock_in_time')

    if metric == 'cashflow':
        selected_entries = cashflow_entries
        selected_total = cashflow_entries.aggregate(total=Sum('montant'))['total'] or 0
        selected_total_is_count = False
    elif metric == 'bank':
        selected_entries = bank_entries
        selected_total = bank_entries.aggregate(total=Sum('amount'))['total'] or 0
        selected_total_is_count = False
    elif metric == 'pointages':
        selected_entries = pointage_entries
        selected_total = pointage_entries.count()
        selected_total_is_count = True
    else:
        selected_entries = loss_entries
        selected_total = loss_entries.aggregate(total=Sum('amount'))['total'] or 0
        selected_total_is_count = False

    context = {
        'site': site,
        'today': today,
        'selected_date': selected_date,
        'period': period,
        'metric': metric,
        'range_start': range_start,
        'range_end': range_end,
        'range_label': range_label,
        'selected_entries': selected_entries,
        'selected_total': selected_total,
        'selected_total_is_count': selected_total_is_count,
        'cashflow_entries': cashflow_entries,
        'bank_entries': bank_entries,
        'losses': loss_entries,
        'pointage_entries': pointage_entries,
        'pertes_total': pertes_total,
        'pertes_caisse': pertes_caisse,
        'pertes_banque': pertes_banque,
        'cash_flow_date': cash_flow_date,
        'bank_deposit_date': bank_deposit_date,
        'ecart_caisse_date': ecart_caisse_date,
        'week_start': week_start,
        'week_end': week_end,
        'week_range_label': week_range_label,
        'cash_flow_week': cash_flow_week,
        'bank_deposit_week': bank_deposit_week,
        'bank_net_week': bank_net_week,
        'pertes_week_total': pertes_week_total,
        'pertes_week_caisse': pertes_week_caisse,
        'pertes_week_banque': pertes_week_banque,
        'caisse_balance_week': caisse_balance_week,
    }
    return render(request, 'admin/site_losses.html', context)


@login_required
@no_cache_view
def admin_add_site_loss(request, site_id):
    """
    Ajouter une perte pour un site.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    today = timezone.localdate()
    date_value = request.GET.get('date', today.strftime('%Y-%m-%d'))
    next_url = _safe_next_url(request) or ''

    if request.method == 'POST':
        date_value = request.POST.get('date', '').strip()
        category = request.POST.get('category', '').strip()
        funding_source = request.POST.get('funding_source', '').strip()
        amount = request.POST.get('amount', '').strip()
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        next_url = _safe_next_url(request) or ''

        if not date_value or not category or not funding_source or not amount or not title:
            messages.error(request, "Date, type de perte, source, montant et titre sont requis.")
            return _render_site_loss_form(request, site, 'create', date_value or today, next_url=next_url)

        try:
            date_obj = datetime.strptime(date_value, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "Format de date invalide.")
            return _render_site_loss_form(request, site, 'create', date_value or today, next_url=next_url)

        valid_categories = {choice[0] for choice in SiteLossEntry.CATEGORY_CHOICES}
        valid_sources = {choice[0] for choice in SiteLossEntry.FUNDING_SOURCE_CHOICES}
        if category not in valid_categories or funding_source not in valid_sources:
            messages.error(request, "Valeur invalide pour le type de perte ou la source des fonds.")
            return _render_site_loss_form(request, site, 'create', date_obj, next_url=next_url)

        try:
            amount_decimal = Decimal(amount)
            if amount_decimal < 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError):
            messages.error(request, "Montant invalide.")
            return _render_site_loss_form(request, site, 'create', date_obj, next_url=next_url)

        loss_entry = SiteLossEntry.objects.create(
            site=site,
            date=date_obj,
            category=category,
            funding_source=funding_source,
            amount=amount_decimal,
            title=title,
            description=description,
            created_by=user,
        )

        AuditLog.log(
            user=user,
            action="CREER",
            description=f"Perte ajoutée sur {site.nom}: {loss_entry.title} ({loss_entry.amount} FC)",
            content_object=loss_entry,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        messages.success(request, "Perte enregistrée avec succès.")
        return _redirect_to_site_losses(request, site, date_obj=date_obj)

    return _render_site_loss_form(request, site, 'create', date_value, next_url=next_url)


@login_required
@no_cache_view
def admin_edit_site_loss(request, site_id, loss_id):
    """
    Modifier une perte existante.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    loss_entry = get_object_or_404(SiteLossEntry, id=loss_id, site=site)
    next_url = _safe_next_url(request) or ''

    if request.method == 'POST':
        motif = request.POST.get('motif', '').strip()
        date_value = request.POST.get('date', '').strip()
        category = request.POST.get('category', '').strip()
        funding_source = request.POST.get('funding_source', '').strip()
        amount = request.POST.get('amount', '').strip()
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        next_url = _safe_next_url(request) or ''

        if not motif:
            messages.error(request, "Le motif de modification est obligatoire.")
            return redirect('admin_edit_site_loss', site_id=site.id, loss_id=loss_entry.id)

        if not date_value or not category or not funding_source or not amount or not title:
            messages.error(request, "Date, type de perte, source, montant et titre sont requis.")
            return redirect('admin_edit_site_loss', site_id=site.id, loss_id=loss_entry.id)

        try:
            date_obj = datetime.strptime(date_value, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "Format de date invalide.")
            return redirect('admin_edit_site_loss', site_id=site.id, loss_id=loss_entry.id)

        valid_categories = {choice[0] for choice in SiteLossEntry.CATEGORY_CHOICES}
        valid_sources = {choice[0] for choice in SiteLossEntry.FUNDING_SOURCE_CHOICES}
        if category not in valid_categories or funding_source not in valid_sources:
            messages.error(request, "Valeur invalide pour le type de perte ou la source des fonds.")
            return redirect('admin_edit_site_loss', site_id=site.id, loss_id=loss_entry.id)

        try:
            amount_decimal = Decimal(amount)
            if amount_decimal < 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError):
            messages.error(request, "Montant invalide.")
            return redirect('admin_edit_site_loss', site_id=site.id, loss_id=loss_entry.id)

        donnees_avant = {
            'date': str(loss_entry.date),
            'category': loss_entry.category,
            'funding_source': loss_entry.funding_source,
            'amount': str(loss_entry.amount),
            'title': loss_entry.title,
            'description': loss_entry.description,
        }

        loss_entry.date = date_obj
        loss_entry.category = category
        loss_entry.funding_source = funding_source
        loss_entry.amount = amount_decimal
        loss_entry.title = title
        loss_entry.description = description
        loss_entry.save()

        donnees_apres = {
            'date': str(loss_entry.date),
            'category': loss_entry.category,
            'funding_source': loss_entry.funding_source,
            'amount': str(loss_entry.amount),
            'title': loss_entry.title,
            'description': loss_entry.description,
        }

        AuditLog.log(
            user=user,
            action="MODIFIER",
            description=f"Perte modifiée sur {site.nom}: {loss_entry.title} ({loss_entry.amount} FC)",
            motif=motif,
            content_object=loss_entry,
            donnees_avant=donnees_avant,
            donnees_apres=donnees_apres,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        messages.success(request, "Perte modifiée avec succès.")
        return _redirect_to_site_losses(request, site, date_obj=loss_entry.date)

    return _render_site_loss_form(
        request,
        site,
        'edit',
        loss_entry.date,
        next_url=next_url,
        loss_entry=loss_entry,
    )


@login_required
@no_cache_view
def admin_delete_site_loss(request, site_id, loss_id):
    """
    Supprimer une perte existante.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    loss_entry = get_object_or_404(SiteLossEntry, id=loss_id, site=site)
    next_url = _safe_next_url(request) or ''

    if request.method == 'POST':
        motif = request.POST.get('motif', '').strip()
        if not motif:
            messages.error(request, "Le motif de suppression est obligatoire.")
            return redirect('admin_delete_site_loss', site_id=site.id, loss_id=loss_entry.id)

        donnees_avant = {
            'date': str(loss_entry.date),
            'category': loss_entry.category,
            'funding_source': loss_entry.funding_source,
            'amount': str(loss_entry.amount),
            'title': loss_entry.title,
            'description': loss_entry.description,
        }
        deleted_title = loss_entry.title
        deleted_amount = loss_entry.amount
        deleted_date = loss_entry.date
        loss_entry.delete()

        AuditLog.log(
            user=user,
            action="SUPPRIMER",
            description=f"Perte supprimée sur {site.nom}: {deleted_title} ({deleted_amount} FC)",
            motif=motif,
            donnees_avant=donnees_avant,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        messages.success(request, "Perte supprimée avec succès.")
        return _redirect_to_site_losses(request, site, date_obj=deleted_date)

    return render(request, 'admin/site_loss_delete.html', {
        'site': site,
        'loss_entry': loss_entry,
        'next_url': next_url,
    })


PAYMENT_RECEIPT_SHARE_SALT = "shinecongo-payment-receipt-share"


def _build_payment_receipt_share_token(payment):
    """
    Génère un jeton signé pour exposer la fiche de paiement en lecture seule.
    """
    return signing.dumps(
        {
            "payment_id": payment.id,
            "site_id": str(payment.site_id),
        },
        salt=PAYMENT_RECEIPT_SHARE_SALT,
        compress=True,
    )


def _build_payment_receipt_share_meta(request, payment):
    """
    Prépare les liens et textes de partage pour une fiche de paiement.
    """
    employee_name = payment.employee_profile.user.get_full_name() or payment.employee_profile.user.username
    share_token = _build_payment_receipt_share_token(payment)
    share_url = request.build_absolute_uri(
        reverse("shared_employee_payment_receipt", kwargs={"token": share_token})
    )
    share_pdf_url = request.build_absolute_uri(
        reverse("shared_employee_payment_receipt_pdf", kwargs={"token": share_token})
    )
    share_filename = f"fiche-paiement-{employee_name.lower().replace(' ', '-')}-{payment.payment_date:%Y%m%d}.pdf"
    share_title = f"Fiche de paiement - {employee_name}"
    share_text = (
        f"Bonjour, voici la fiche de paiement de {employee_name} pour {payment.site.nom} "
        f"({payment.period_start.strftime('%d/%m/%Y')} au {payment.period_end.strftime('%d/%m/%Y')}) "
        f"pour un montant de ${payment.amount_paid_usd:.2f} USD."
    )
    share_body = f"{share_text}\n{share_url}"
    return {
        "share_url": share_url,
        "share_pdf_url": share_pdf_url,
        "share_filename": share_filename,
        "share_title": share_title,
        "share_text": share_text,
        "share_body": share_body,
        "whatsapp_share_url": "https://web.whatsapp.com/",
        "email_share_url": f"mailto:?subject={quote(share_title)}&body={quote(share_body)}",
    }


def _get_shared_payment_from_token(token):
    """
    Résout une fiche de paiement depuis un jeton signé.
    """
    try:
        payload = signing.loads(token, salt=PAYMENT_RECEIPT_SHARE_SALT)
    except signing.BadSignature as exc:
        raise Http404("Lien de partage invalide.") from exc

    site_id = payload.get("site_id")
    payment_id = payload.get("payment_id")
    if not site_id or not payment_id:
        raise Http404("Lien de partage invalide.")

    return get_object_or_404(
        EmployeePayment.objects.select_related("site", "employee_profile", "employee_profile__user", "created_by"),
        id=payment_id,
        site__id=site_id,
    )


def _build_site_employee_management_context(request, site):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    active_tab = request.GET.get('tab', 'team').strip().lower()
    if active_tab not in {'team', 'payments', 'performance'}:
        active_tab = 'team'

    site_employees = list(
        UserProfile.objects.filter(
            site=site,
            role__in=UserProfile.SITE_STAFF_ROLES,
        ).select_related('user').order_by('-actif', 'user__first_name', 'user__last_name', 'user__username')
    )
    active_employee_count = sum(1 for profile in site_employees if profile.actif and profile.user.is_active)
    inactive_employee_count = len(site_employees) - active_employee_count
    salary_defined_count = sum(1 for profile in site_employees if profile.salaire_mensuel_usd)
    wash_employee_count = sum(1 for profile in site_employees if profile.is_employe())
    camera_controller_count = sum(1 for profile in site_employees if profile.is_camera_controller())

    selected_employee = request.GET.get('employee')
    if selected_employee and active_tab == 'team':
        active_tab = 'payments'
    payment_records_qs = EmployeePayment.objects.filter(site=site).select_related(
        'employee_profile',
        'employee_profile__user',
        'created_by',
    )
    if selected_employee:
        payment_records_qs = payment_records_qs.filter(employee_profile_id=selected_employee)
    payment_records = list(payment_records_qs.order_by('-payment_date', '-created_at'))
    payment_total_usd = sum((payment.amount_paid_usd for payment in payment_records), Decimal("0"))
    unique_paid_employee_count = len({payment.employee_profile_id for payment in payment_records})
    latest_payment = payment_records[0] if payment_records else None
    for payment in payment_records:
        share_meta = _build_payment_receipt_share_meta(request, payment)
        payment.share_url = share_meta["share_url"]
        payment.share_pdf_url = share_meta["share_pdf_url"]
        payment.share_filename = share_meta["share_filename"]
        payment.share_title = share_meta["share_title"]
        payment.share_text = share_meta["share_text"]
        payment.share_body = share_meta["share_body"]
        payment.whatsapp_share_url = share_meta["whatsapp_share_url"]
        payment.email_share_url = share_meta["email_share_url"]

    productivity_qs = CarWash.objects.filter(
        site=site,
        is_system_generated=False,
    )
    team_total_lavages = productivity_qs.count()
    team_total_cash_flow = productivity_qs.aggregate(total=Sum('montant'))['total'] or Decimal("0")
    team_month_lavages = productivity_qs.filter(date__gte=month_start, date__lte=today).count()
    team_month_cash_flow = (
        productivity_qs.filter(date__gte=month_start, date__lte=today).aggregate(total=Sum('montant'))['total']
        or Decimal("0")
    )

    reports_month_count = ShiftDay.objects.filter(
        site=site,
        date__gte=month_start,
        date__lte=today,
        daily_report_confirmed=True,
    ).count()
    payments_month_total_usd = (
        EmployeePayment.objects.filter(
            site=site,
            payment_date__gte=month_start,
            payment_date__lte=today,
        ).aggregate(total=Sum('amount_paid_usd'))['total']
        or Decimal("0")
    )

    lavages_totals = {
        item['employe_id']: item
        for item in productivity_qs.values('employe_id').annotate(
            total_lavages=Count('id'),
            total_fc=Sum('montant'),
            last_lavage_date=Max('date'),
        )
    }
    lavages_month_totals = {
        item['employe_id']: item
        for item in productivity_qs.filter(date__gte=month_start, date__lte=today).values('employe_id').annotate(
            month_lavages=Count('id'),
            month_fc=Sum('montant'),
        )
    }
    reports_totals = {
        item['employe_id']: item
        for item in ShiftDay.objects.filter(site=site, daily_report_confirmed=True).values('employe_id').annotate(
            total_reports=Count('id'),
            last_report_date=Max('date'),
        )
    }
    reports_month_totals = {
        item['employe_id']: item
        for item in ShiftDay.objects.filter(
            site=site,
            daily_report_confirmed=True,
            date__gte=month_start,
            date__lte=today,
        ).values('employe_id').annotate(month_reports=Count('id'))
    }
    issues_totals = {
        item['employe_id']: item
        for item in IssueReport.objects.filter(site=site).values('employe_id').annotate(
            total_issues=Count('id'),
            open_issues=Count('id', filter=Q(statut__in=['OUVERT', 'EN_COURS'])),
        )
    }
    payment_totals = {
        item['employee_profile_id']: item
        for item in EmployeePayment.objects.filter(site=site).values('employee_profile_id').annotate(
            total_payments=Count('id'),
            total_paid_usd=Sum('amount_paid_usd'),
            last_payment_date=Max('payment_date'),
        )
    }
    camera_report_totals = {
        item['controller_id']: item
        for item in CameraOperatorDailyReport.objects.filter(
            site=site,
            is_submitted=True,
        ).values('controller_id').annotate(
            total_camera_reports=Count('id'),
            total_camera_vehicles=Sum('total_vehicles'),
            total_camera_screenshots=Sum('screenshots_count'),
            last_camera_report_date=Max('date'),
        )
    }
    camera_report_month_totals = {
        item['controller_id']: item
        for item in CameraOperatorDailyReport.objects.filter(
            site=site,
            is_submitted=True,
            date__gte=month_start,
            date__lte=today,
        ).values('controller_id').annotate(
            month_camera_reports=Count('id'),
            month_camera_vehicles=Sum('total_vehicles'),
        )
    }

    employee_rows = []
    for profile in site_employees:
        total_stats = lavages_totals.get(profile.user_id, {})
        month_stats = lavages_month_totals.get(profile.user_id, {})
        report_stats = reports_totals.get(profile.user_id, {})
        month_report_stats = reports_month_totals.get(profile.user_id, {})
        issue_stats = issues_totals.get(profile.user_id, {})
        payment_stats = payment_totals.get(profile.id, {})
        camera_stats = camera_report_totals.get(profile.user_id, {})
        camera_month_stats = camera_report_month_totals.get(profile.user_id, {})

        last_activity = total_stats.get('last_lavage_date') or report_stats.get('last_report_date')
        report_date = report_stats.get('last_report_date')
        if report_date and (not last_activity or report_date > last_activity):
            last_activity = report_date
        camera_report_date = camera_stats.get('last_camera_report_date')
        if camera_report_date and (not last_activity or camera_report_date > last_activity):
            last_activity = camera_report_date

        employee_rows.append({
            'profile': profile,
            'role_label': profile.get_role_display(),
            'total_lavages': total_stats.get('total_lavages', 0) or 0,
            'total_fc': total_stats.get('total_fc') or Decimal("0"),
            'month_lavages': month_stats.get('month_lavages', 0) or 0,
            'month_fc': month_stats.get('month_fc') or Decimal("0"),
            'total_reports': report_stats.get('total_reports', 0) or 0,
            'month_reports': month_report_stats.get('month_reports', 0) or 0,
            'total_issues': issue_stats.get('total_issues', 0) or 0,
            'open_issues': issue_stats.get('open_issues', 0) or 0,
            'total_camera_reports': camera_stats.get('total_camera_reports', 0) or 0,
            'month_camera_reports': camera_month_stats.get('month_camera_reports', 0) or 0,
            'total_camera_vehicles': camera_stats.get('total_camera_vehicles', 0) or 0,
            'month_camera_vehicles': camera_month_stats.get('month_camera_vehicles', 0) or 0,
            'total_camera_screenshots': camera_stats.get('total_camera_screenshots', 0) or 0,
            'total_payments': payment_stats.get('total_payments', 0) or 0,
            'total_paid_usd': payment_stats.get('total_paid_usd') or Decimal("0"),
            'last_payment_date': payment_stats.get('last_payment_date'),
            'last_activity': last_activity,
        })

    top_performers_month = sorted(
        employee_rows,
        key=lambda row: (row['month_fc'], row['month_lavages'], row['total_fc']),
        reverse=True,
    )[:5]
    top_performers_total = sorted(
        employee_rows,
        key=lambda row: (row['total_fc'], row['total_lavages'], row['total_paid_usd']),
        reverse=True,
    )[:5]
    employees_missing_salary = [row for row in employee_rows if not row['profile'].salaire_mensuel_usd]

    return {
        'site': site,
        'today': today,
        'month_start': month_start,
        'active_tab': active_tab,
        'site_employees': site_employees,
        'employee_rows': employee_rows,
        'active_employee_count': active_employee_count,
        'inactive_employee_count': inactive_employee_count,
        'salary_defined_count': salary_defined_count,
        'wash_employee_count': wash_employee_count,
        'camera_controller_count': camera_controller_count,
        'payment_records': payment_records,
        'payment_total_usd': payment_total_usd,
        'payment_records_count': len(payment_records),
        'unique_paid_employee_count': unique_paid_employee_count,
        'selected_employee': str(selected_employee) if selected_employee else '',
        'latest_payment': latest_payment,
        'team_total_lavages': team_total_lavages,
        'team_total_cash_flow': team_total_cash_flow,
        'team_month_lavages': team_month_lavages,
        'team_month_cash_flow': team_month_cash_flow,
        'reports_month_count': reports_month_count,
        'payments_month_total_usd': payments_month_total_usd,
        'top_performers_month': top_performers_month,
        'top_performers_total': top_performers_total,
        'employees_missing_salary': employees_missing_salary,
    }


def _camera_monitoring_url(site, selected_date=None, anchor=""):
    """
    Construit l'URL du hub caméras du site en conservant la date active.
    """
    base_url = reverse("admin_site_camera_monitoring", kwargs={"site_id": site.id})
    if selected_date:
        base_url = f"{base_url}?date={selected_date:%Y-%m-%d}"
    if anchor:
        return f"{base_url}#{anchor}"
    return base_url


def _camera_controller_portal_url(site, controller_profile, selected_date=None):
    base_url = reverse(
        "admin_camera_controller_portal",
        kwargs={"site_id": site.id, "profile_id": controller_profile.id},
    )
    if selected_date:
        return f"{base_url}?date={selected_date:%Y-%m-%d}"
    return base_url


def _parse_camera_selected_date(request):
    """
    Résout la date active pour le module caméras.
    """
    raw_value = request.GET.get("date") or request.POST.get("selected_date") or request.POST.get("report-date")
    if raw_value:
        try:
            return datetime.strptime(raw_value, "%Y-%m-%d").date()
        except ValueError:
            pass
    return timezone.localdate()


def _build_camera_monitoring_context(request, site, selected_date, camera_form=None, report_form=None):
    """
    Construit le contexte du tableau de bord caméras pour un site donné.
    """
    today = timezone.localdate()
    current_month_start = today.replace(day=1)
    current_month_end = current_month_start.replace(
        day=calendar.monthrange(current_month_start.year, current_month_start.month)[1]
    )
    selected_month_start = _parse_month_filter(request.GET.get("month")) if request.GET.get("month") else selected_date.replace(day=1)
    selected_month_end = selected_month_start.replace(
        day=calendar.monthrange(selected_month_start.year, selected_month_start.month)[1]
    )
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    cameras = list(
        Camera.objects.filter(site=site)
        .annotate(evidence_count=Count("video_evidences"))
        .order_by("camera_number", "name")
    )
    camera_controller_profiles = list(
        UserProfile.objects.filter(
            site=site,
            role=UserProfile.CAMERA_CONTROLLER_ROLE,
            actif=True,
        )
        .select_related("user")
        .order_by("user__first_name", "user__last_name", "user__username")
    )
    reports_qs = DailyCameraReport.objects.filter(site=site)
    selected_report = (
        reports_qs.filter(date=selected_date)
        .select_related("created_by", "reviewed_by")
        .prefetch_related("video_evidences__camera", "video_evidences__uploaded_by")
        .first()
    )
    month_reports = list(
        reports_qs.filter(date__gte=selected_month_start, date__lte=selected_month_end)
        .select_related("created_by", "reviewed_by")
        .annotate(evidence_count=Count("video_evidences"))
        .order_by("-date", "-created_at")
    )
    operator_reports_qs = CameraOperatorDailyReport.objects.filter(
        site=site,
        date__gte=selected_month_start,
        date__lte=selected_month_end,
    )
    operator_reports = list(
        operator_reports_qs.select_related("controller", "controller__userprofile")
        .prefetch_related(
            Prefetch(
                "observations",
                queryset=CameraObservation.objects.select_related("camera").prefetch_related("evidences").order_by("-created_at"),
            )
        )
        .order_by("-date", "controller__first_name", "controller__last_name", "controller__username")
    )
    selected_operator_reports = [report for report in operator_reports if report.date == selected_date]
    selected_operator_reports_by_controller = {report.controller_id: report for report in selected_operator_reports}
    controller_activity = []
    for controller_profile in camera_controller_profiles:
        controller_report = selected_operator_reports_by_controller.get(controller_profile.user_id)
        latest_observation = None
        if controller_report:
            prefetched_observations = list(controller_report.observations.all())
            latest_observation = prefetched_observations[0] if prefetched_observations else None
            controller_report.manage_url = _camera_controller_portal_url(site, controller_profile, selected_date)
            controller_report.status_label = "Rapport final soumis" if controller_report.is_submitted else "Brouillon en cours"
            controller_report.status_class = (
                "camera-state--active" if controller_report.is_submitted else "camera-state--draft"
            )

        controller_activity.append(
            {
                "profile": controller_profile,
                "report": controller_report,
                "manage_url": _camera_controller_portal_url(site, controller_profile, selected_date),
                "status_label": (
                    "Rapport final soumis"
                    if controller_report and controller_report.is_submitted
                    else ("Brouillon en cours" if controller_report else "Aucune activité")
                ),
                "status_class": (
                    "camera-state--active"
                    if controller_report and controller_report.is_submitted
                    else ("camera-state--draft" if controller_report else "camera-state--idle")
                ),
                "latest_observation": latest_observation,
                "last_activity_at": (
                    controller_report.submitted_at
                    if controller_report and controller_report.is_submitted and controller_report.submitted_at
                    else (
                        latest_observation.created_at
                        if latest_observation
                        else (controller_report.updated_at if controller_report else None)
                    )
                ),
            }
        )
    today_report = reports_qs.filter(date=today).first()
    weekly_totals = reports_qs.filter(date__gte=week_start, date__lte=week_end).aggregate(
        total_vehicles=Sum("total_vehicles"),
        expected_revenue=Sum("expected_revenue"),
    )
    monthly_reports_qs = reports_qs.filter(date__gte=current_month_start, date__lte=current_month_end)
    monthly_totals = monthly_reports_qs.aggregate(
        total_vehicles=Sum("total_vehicles"),
        expected_revenue=Sum("expected_revenue"),
    )
    monthly_evidence_count = VideoEvidence.objects.filter(
        daily_report__site=site,
        daily_report__date__gte=current_month_start,
        daily_report__date__lte=current_month_end,
    ).count()
    selected_month_totals = reports_qs.filter(
        date__gte=selected_month_start,
        date__lte=selected_month_end,
    ).aggregate(
        cars_total=Sum("final_cars_count"),
        motos_total=Sum("final_motos_count"),
        three_wheelers_total=Sum("final_three_wheelers_count"),
        total_vehicles=Sum("total_vehicles"),
        expected_revenue=Sum("expected_revenue"),
    )
    total_evidence_count = VideoEvidence.objects.filter(daily_report__site=site).count()
    operator_month_totals = operator_reports_qs.aggregate(
        total_reports=Count("id"),
        total_submitted_reports=Count("id", filter=Q(is_submitted=True)),
        total_draft_reports=Count("id", filter=Q(is_submitted=False)),
        total_vehicles=Sum("total_vehicles"),
        total_screenshots=Sum("screenshots_count"),
        total_time_proofs=Sum("time_proof_count"),
    )

    for report in operator_reports:
        controller_profile = getattr(report.controller, "userprofile", None)
        if controller_profile:
            report.manage_url = _camera_controller_portal_url(site, controller_profile, report.date)
        else:
            report.manage_url = _camera_monitoring_url(site, report.date)
        report.status_label = "Rapport final soumis" if report.is_submitted else "Brouillon en cours"
        report.status_class = "camera-state--active" if report.is_submitted else "camera-state--draft"
        observations = list(report.observations.all())
        report.latest_observation = observations[0] if observations else None

    if camera_form is None:
        camera_form = CameraForm(prefix="camera", initial={"is_active": True})
    if report_form is None:
        report_form = DailyCameraReportForm(
            prefix="report",
            instance=selected_report,
            initial={"date": selected_date},
        )

    return {
        "site": site,
        "today": today,
        "selected_date": selected_date,
        "selected_month_start": selected_month_start,
        "selected_month_end": selected_month_end,
        "selected_month_label": _month_label(selected_month_start),
        "camera_form": camera_form,
        "report_form": report_form,
        "cameras": cameras,
        "selected_report": selected_report,
        "selected_report_evidences": list(selected_report.video_evidences.all()) if selected_report else [],
        "month_reports": month_reports,
        "operator_reports": operator_reports,
        "selected_operator_reports": selected_operator_reports,
        "camera_controller_profiles": camera_controller_profiles,
        "controller_activity": controller_activity,
        "controllers_on_site_count": len(camera_controller_profiles),
        "controllers_with_activity_count": sum(1 for item in controller_activity if item["report"]),
        "selected_date_operator_reports_count": len(selected_operator_reports),
        "selected_date_operator_submitted_count": sum(
            1 for item in selected_operator_reports if item.is_submitted
        ),
        "selected_date_operator_total_vehicles": sum(
            item.total_vehicles for item in selected_operator_reports
        ),
        "active_camera_count": sum(1 for camera in cameras if camera.is_active),
        "inactive_camera_count": sum(1 for camera in cameras if not camera.is_active),
        "total_evidence_count": total_evidence_count,
        "operator_reports_count": operator_month_totals["total_reports"] or 0,
        "operator_submitted_reports_count": operator_month_totals["total_submitted_reports"] or 0,
        "operator_draft_reports_count": operator_month_totals["total_draft_reports"] or 0,
        "operator_total_vehicles": operator_month_totals["total_vehicles"] or 0,
        "operator_total_screenshots": operator_month_totals["total_screenshots"] or 0,
        "operator_total_time_proofs": operator_month_totals["total_time_proofs"] or 0,
        "today_cars_count": (
            today_report.final_cars_count
            if today_report and today_report.final_cars_count is not None
            else (today_report.cars_count if today_report else 0)
        ) or 0,
        "today_motos_count": (
            today_report.final_motos_count
            if today_report and today_report.final_motos_count is not None
            else (today_report.motos_count if today_report else 0)
        ) or 0,
        "today_three_wheelers_count": (
            today_report.final_three_wheelers_count
            if today_report and today_report.final_three_wheelers_count is not None
            else (today_report.three_wheelers_count if today_report else 0)
        ) or 0,
        "today_expected_revenue": _to_decimal_amount(today_report.expected_revenue if today_report else 0),
        "weekly_total_vehicles": weekly_totals["total_vehicles"] or 0,
        "weekly_expected_revenue": _to_decimal_amount(weekly_totals["expected_revenue"]),
        "monthly_total_vehicles": monthly_totals["total_vehicles"] or 0,
        "monthly_expected_revenue": _to_decimal_amount(monthly_totals["expected_revenue"]),
        "monthly_evidence_count": monthly_evidence_count,
        "selected_month_cars_total": selected_month_totals["cars_total"] or 0,
        "selected_month_motos_total": selected_month_totals["motos_total"] or 0,
        "selected_month_three_wheelers_total": selected_month_totals["three_wheelers_total"] or 0,
        "selected_month_total_vehicles": selected_month_totals["total_vehicles"] or 0,
        "selected_month_expected_revenue": _to_decimal_amount(selected_month_totals["expected_revenue"]),
    }


@login_required
@no_cache_view
def admin_site_camera_monitoring(request, site_id):
    """
    Hub admin pour la supervision des caméras, du comptage manuel et des preuves vidéo.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    selected_date = _parse_camera_selected_date(request)
    selected_report = DailyCameraReport.objects.filter(site=site, date=selected_date).first()

    camera_form = CameraForm(prefix="camera", initial={"is_active": True})
    report_form = DailyCameraReportForm(
        prefix="report",
        instance=selected_report,
        initial={"date": selected_date},
    )

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "save_camera":
            camera_form = CameraForm(request.POST, prefix="camera")
            if camera_form.is_valid():
                camera = camera_form.save(commit=False)
                camera.site = site
                camera.save()

                AuditLog.log(
                    user=user,
                    action="CREER",
                    description=f"Caméra ajoutée sur {site.nom}: caméra {camera.camera_number} ({camera.name})",
                    content_object=camera,
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request),
                )

                messages.success(request, f'Caméra "{camera.name}" enregistrée avec succès.')
                return redirect(_camera_monitoring_url(site, selected_date, "camera-inventory"))

        elif action == "save_daily_camera_report":
            report_form = DailyCameraReportForm(
                request.POST,
                prefix="report",
                instance=selected_report,
            )
            if report_form.is_valid():
                report = report_form.save(commit=False)
                report.site = site
                if not report.created_by_id:
                    report.created_by = user
                report.save()

                AuditLog.log(
                    user=user,
                    action="CREER" if selected_report is None else "MODIFIER",
                    description=(
                        f"Rapport caméra {'créé' if selected_report is None else 'mis à jour'} sur {site.nom} "
                        f"pour le {report.date:%d/%m/%Y}"
                    ),
                    content_object=report,
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request),
                )

                messages.success(request, "Rapport caméra enregistré. Vous pouvez maintenant ajouter les preuves vidéo.")
                return redirect("admin_site_camera_report_detail", site_id=site.id, report_id=report.id)

    context = _build_camera_monitoring_context(
        request,
        site,
        selected_date,
        camera_form=camera_form,
        report_form=report_form,
    )
    return render(request, "admin/site_camera_monitoring.html", context)


@login_required
@no_cache_view
def admin_edit_site_camera(request, site_id, camera_id):
    """
    Modifier une caméra déjà enregistrée pour un site.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    camera = get_object_or_404(Camera, id=camera_id, site=site)
    next_url = _safe_next_url(request) or _camera_monitoring_url(site, timezone.localdate(), "camera-inventory")

    if request.method == "POST":
        form = CameraForm(request.POST, instance=camera)
        if form.is_valid():
            camera = form.save()
            AuditLog.log(
                user=user,
                action="MODIFIER",
                description=f"Caméra mise à jour sur {site.nom}: caméra {camera.camera_number} ({camera.name})",
                content_object=camera,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )
            messages.success(request, "Caméra mise à jour avec succès.")
            return redirect(next_url)
    else:
        form = CameraForm(instance=camera)

    return render(
        request,
        "admin/site_camera_form.html",
        {
            "site": site,
            "camera": camera,
            "form": form,
            "next_url": next_url,
        },
    )


@login_required
@no_cache_view
def admin_site_camera_report_detail(request, site_id, report_id):
    """
    Détail d'un rapport caméra quotidien avec upload des preuves.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    report = get_object_or_404(
        DailyCameraReport.objects.select_related("site", "created_by", "reviewed_by").prefetch_related(
            "video_evidences__camera",
            "video_evidences__uploaded_by",
        ),
        id=report_id,
        site=site,
    )

    evidence_form = VideoEvidenceForm(
        prefix="evidence",
        site=site,
        daily_report=report,
    )

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "upload_video_evidence":
            evidence_form = VideoEvidenceForm(
                request.POST,
                request.FILES,
                prefix="evidence",
                site=site,
                daily_report=report,
            )
            if evidence_form.is_valid():
                evidence = evidence_form.save(commit=False)
                evidence.daily_report = report
                evidence.uploaded_by = user
                evidence.save()

                AuditLog.log(
                    user=user,
                    action="CREER",
                    description=(
                        f"Preuve caméra ajoutée sur {site.nom} le {report.date:%d/%m/%Y}: "
                        f"{evidence.title} ({evidence.get_evidence_type_display()})"
                    ),
                    content_object=evidence,
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request),
                )

                messages.success(request, "Preuve vidéo enregistrée avec succès.")
                return redirect("admin_site_camera_report_detail", site_id=site.id, report_id=report.id)

    evidences = list(report.video_evidences.all())
    evidence_type_counts = {}
    for evidence in evidences:
        evidence_type_counts.setdefault(evidence.get_evidence_type_display(), 0)
        evidence_type_counts[evidence.get_evidence_type_display()] += 1

    return render(
        request,
        "admin/site_camera_report_detail.html",
        {
            "site": site,
            "report": report,
            "evidence_form": evidence_form,
            "evidences": evidences,
            "evidence_type_counts": evidence_type_counts,
            "monitoring_url": _camera_monitoring_url(site, report.date, "daily-report-form"),
        },
    )


@login_required
@no_cache_view
def admin_delete_video_evidence(request, site_id, evidence_id):
    """
    Supprimer une preuve vidéo/capture rattachée à un rapport caméra.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    evidence = get_object_or_404(
        VideoEvidence.objects.select_related("daily_report", "camera"),
        id=evidence_id,
        daily_report__site=site,
    )
    report = evidence.daily_report

    if request.method == "POST":
        evidence_title = evidence.title
        if evidence.uploaded_file:
            evidence.uploaded_file.delete(save=False)
        evidence.delete()

        AuditLog.log(
            user=user,
            action="SUPPRIMER",
            description=f"Preuve caméra supprimée sur {site.nom}: {evidence_title}",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        messages.success(request, "Preuve vidéo supprimée avec succès.")
        return redirect("admin_site_camera_report_detail", site_id=site.id, report_id=report.id)

    return render(
        request,
        "admin/delete_video_evidence.html",
        {
            "site": site,
            "evidence": evidence,
            "report": report,
        },
    )


@login_required
@no_cache_view
def admin_download_video_evidence(request, site_id, evidence_id):
    """
    Télécharge une preuve caméra en pièce jointe.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette action est réservée aux administrateurs.")
        return redirect("dashboard")

    site = get_object_or_404(Location, id=site_id)
    evidence = get_object_or_404(
        VideoEvidence.objects.select_related("daily_report", "camera"),
        id=evidence_id,
        daily_report__site=site,
    )
    if not evidence.uploaded_file:
        raise Http404("Fichier introuvable.")

    file_handle = evidence.uploaded_file.open("rb")
    filename = evidence.filename() or f"preuve-camera-{evidence.id}"
    return FileResponse(file_handle, as_attachment=True, filename=filename)


def _build_payment_receipt_pdf(payment):
    """
    Génère un PDF de la fiche de paiement.
    """
    logo_path = finders.find("favicon.png") or ""
    html = render_to_string(
        "admin/payment_receipt_pdf.html",
        {
            "site": payment.site,
            "payment": payment,
            "company_name": "Shine Congo",
            "logo_path": logo_path,
        },
    )
    result = BytesIO()
    pdf = pisa.CreatePDF(src=html, dest=result, encoding="utf-8")
    if pdf.err:
        raise ValueError("Impossible de générer le PDF de la fiche de paiement.")
    return result.getvalue()


def _build_payment_receipt_pdf_response(payment, download=False):
    """
    Retourne la réponse HTTP PDF de la fiche de paiement.
    """
    employee_name = payment.employee_profile.user.get_full_name() or payment.employee_profile.user.username
    filename = f"fiche-paiement-{employee_name.lower().replace(' ', '-')}-{payment.payment_date:%Y%m%d}.pdf"
    pdf_bytes = _build_payment_receipt_pdf(payment)
    disposition = "attachment" if download else "inline"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response


@login_required
@no_cache_view
def admin_site_documents(request, site_id):
    """
    Vue documentaire du site.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)

    documents_queryset = SiteDocument.objects.filter(site=site).select_related('uploaded_by').order_by('-uploaded_at')
    documents_total_count = documents_queryset.count()
    documents_by_type = {}
    media_documents_count = 0
    for doc in documents_queryset:
        file_type = doc.file_type
        if file_type not in documents_by_type:
            documents_by_type[file_type] = []
        documents_by_type[file_type].append(doc)
        if doc.is_image or doc.is_video:
            media_documents_count += 1
    document_type_summaries = []
    for value, label in SiteDocument.FILE_TYPE_CHOICES:
        docs_for_type = documents_by_type.get(value, [])
        document_type_summaries.append({
            "value": value,
            "label": label,
            "count": len(docs_for_type),
            "documents": docs_for_type,
        })
    
    filter_type = request.GET.get('type')
    all_documents = documents_queryset
    if filter_type:
        all_documents = documents_queryset.filter(file_type=filter_type)

    latest_document = documents_queryset.first()
    active_document_type_count = sum(1 for summary in document_type_summaries if summary["count"])

    context = {
        'site': site,
        'all_documents': all_documents,
        'documents_by_type': documents_by_type,
        'file_types': SiteDocument.FILE_TYPE_CHOICES,
        'document_type_summaries': document_type_summaries,
        'filter_type': filter_type,
        'documents_total_count': documents_total_count,
        'latest_document': latest_document,
        'active_document_type_count': active_document_type_count,
        'media_documents_count': media_documents_count,
    }
    
    return render(request, 'admin/site_documents.html', context)


@login_required
@no_cache_view
def admin_site_employees(request, site_id):
    """
    Hub RH du site: équipe, rémunérations et productivité.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    context = _build_site_employee_management_context(request, site)
    return render(request, 'admin/site_employees.html', context)


@login_required
@no_cache_view
def admin_site_employee_portal(request, site_id, profile_id):
    """
    Portail détaillé d'un membre du site (infos, CV, paiements, performance).
    """
    user = request.user
    ensure_superuser_admin_profile(user)
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    profile = get_object_or_404(
        UserProfile.objects.select_related('user', 'site'),
        id=profile_id,
        site=site,
        role__in=UserProfile.SITE_STAFF_ROLES,
    )

    if request.method == 'POST':
        action = request.POST.get('action', '').strip()

        if action == 'upload_photo':
            photo_file = request.FILES.get('profile_photo')
            if not photo_file:
                messages.error(request, "Veuillez sélectionner une photo.")
                return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

            filename = photo_file.name.lower()
            allowed_extensions = ('.jpg', '.jpeg', '.png', '.webp')
            if not filename.endswith(allowed_extensions):
                messages.error(request, "Format image non supporté. Utilisez JPG, PNG ou WEBP.")
                return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

            max_size = 5 * 1024 * 1024  # 5 MB
            if photo_file.size > max_size:
                messages.error(request, "La photo dépasse la limite de 5 MB.")
                return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

            old_photo_name = profile.photo_filename() if profile.profile_photo else ""
            if profile.profile_photo:
                profile.profile_photo.delete(save=False)

            profile.profile_photo = photo_file
            profile.save(update_fields=['profile_photo', 'updated_at'])

            AuditLog.log(
                user=user,
                action="MODIFIER",
                description=f"Photo employé mise à jour pour {profile.user.get_full_name() or profile.user.username}",
                donnees_avant={'photo': old_photo_name or None},
                donnees_apres={'photo': profile.photo_filename()},
                content_object=profile,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            messages.success(request, "Photo employé uploadée avec succès.")
            return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

        if action == 'delete_photo':
            if not profile.profile_photo:
                messages.warning(request, "Aucune photo à supprimer.")
                return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

            deleted_photo_name = profile.photo_filename()
            profile.profile_photo.delete(save=False)
            profile.profile_photo = None
            profile.save(update_fields=['profile_photo', 'updated_at'])

            AuditLog.log(
                user=user,
                action="SUPPRIMER",
                description=f"Photo employé supprimée pour {profile.user.get_full_name() or profile.user.username}",
                donnees_avant={'photo': deleted_photo_name},
                donnees_apres={'photo': None},
                content_object=profile,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            messages.success(request, "Photo employé supprimée avec succès.")
            return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

        if action == 'upload_cv':
            cv_file = request.FILES.get('cv_file')
            if not cv_file:
                messages.error(request, "Veuillez sélectionner un fichier CV.")
                return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

            filename = cv_file.name.lower()
            allowed_extensions = ('.pdf', '.doc', '.docx')
            if not filename.endswith(allowed_extensions):
                messages.error(request, "Format CV non supporté. Utilisez PDF, DOC ou DOCX.")
                return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

            max_size = 10 * 1024 * 1024  # 10 MB
            if cv_file.size > max_size:
                messages.error(request, "Le CV dépasse la limite de 10 MB.")
                return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

            old_cv_name = profile.cv_filename() if profile.cv_file else ""
            if profile.cv_file:
                profile.cv_file.delete(save=False)

            profile.cv_file = cv_file
            profile.save(update_fields=['cv_file', 'updated_at'])

            AuditLog.log(
                user=user,
                action="MODIFIER",
                description=f"CV mis à jour pour {profile.user.get_full_name() or profile.user.username}",
                donnees_avant={'cv': old_cv_name or None},
                donnees_apres={'cv': profile.cv_filename()},
                content_object=profile,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            messages.success(request, "CV uploadé avec succès.")
            return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

        if action == 'delete_cv':
            if not profile.cv_file:
                messages.warning(request, "Aucun CV à supprimer.")
                return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

            deleted_cv_name = profile.cv_filename()
            profile.cv_file.delete(save=False)
            profile.cv_file = None
            profile.save(update_fields=['cv_file', 'updated_at'])

            AuditLog.log(
                user=user,
                action="SUPPRIMER",
                description=f"CV supprimé pour {profile.user.get_full_name() or profile.user.username}",
                donnees_avant={'cv': deleted_cv_name},
                donnees_apres={'cv': None},
                content_object=profile,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            messages.success(request, "CV supprimé avec succès.")
            return redirect('admin_site_employee_portal', site_id=site.id, profile_id=profile.id)

    today = timezone.localdate()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    lavages_qs = CarWash.objects.filter(site=site, employe=profile.user)
    total_lavages = lavages_qs.count()
    lavages_month = lavages_qs.filter(date__gte=month_start, date__lte=today).count()
    lavages_amount_total = lavages_qs.aggregate(total=Sum('montant'))['total'] or 0
    average_ticket_fc = (lavages_amount_total / total_lavages) if total_lavages else 0
    recent_lavages = lavages_qs.prefetch_related('photos').order_by('-date', '-created_at')[:10]

    pointages_qs = ShiftDay.objects.filter(site=site, employe=profile.user)
    total_pointages = pointages_qs.count()
    completed_pointages = pointages_qs.filter(clock_in_time__isnull=False, clock_out_time__isnull=False).count()
    open_pointages = pointages_qs.filter(clock_in_time__isnull=False, clock_out_time__isnull=True).count()
    pointages_month = pointages_qs.filter(date__gte=month_start, date__lte=today, clock_in_time__isnull=False).count()
    today_pointage = pointages_qs.filter(date=today).first()
    latest_daily_report = pointages_qs.filter(daily_report_confirmed=True).order_by('-date', '-updated_at').first()

    recent_pointages_data = []
    for pointage in pointages_qs.order_by('-date', '-clock_in_time')[:12]:
        duration_str = None
        if pointage.clock_in_time and pointage.clock_out_time:
            duration = pointage.clock_out_time - pointage.clock_in_time
            total_seconds = int(duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            duration_str = f"{hours}h{minutes:02d}min"
        recent_pointages_data.append({
            'pointage': pointage,
            'duration': duration_str,
        })

    issues_qs = IssueReport.objects.filter(site=site, employe=profile.user)
    total_issues = issues_qs.count()
    open_issues = issues_qs.filter(statut__in=['OUVERT', 'EN_COURS']).count()

    payment_records = EmployeePayment.objects.filter(
        site=site,
        employee_profile=profile,
    ).select_related('created_by').order_by('-payment_date', '-created_at')
    payments_count = payment_records.count()
    total_paid_usd = payment_records.aggregate(total=Sum('amount_paid_usd'))['total'] or 0
    total_paid_this_year_usd = payment_records.filter(
        payment_date__gte=year_start,
        payment_date__lte=today,
    ).aggregate(total=Sum('amount_paid_usd'))['total'] or 0
    last_payment = payment_records.first()
    camera_reports_qs = CameraOperatorDailyReport.objects.filter(site=site, controller=profile.user)
    camera_reports_submitted_qs = camera_reports_qs.filter(is_submitted=True)

    context = {
        'site': site,
        'employee_profile': profile,
        'staff_role_label': profile.get_role_display(),
        'is_camera_controller': profile.is_camera_controller(),
        'today': today,
        'month_start': month_start,
        'total_lavages': total_lavages,
        'lavages_month': lavages_month,
        'lavages_amount_total': lavages_amount_total,
        'average_ticket_fc': average_ticket_fc,
        'recent_lavages': recent_lavages,
        'total_pointages': total_pointages,
        'completed_pointages': completed_pointages,
        'open_pointages': open_pointages,
        'pointages_month': pointages_month,
        'today_pointage': today_pointage,
        'latest_daily_report': latest_daily_report,
        'recent_pointages_data': recent_pointages_data,
        'total_issues': total_issues,
        'open_issues': open_issues,
        'payment_records': payment_records,
        'payments_count': payments_count,
        'total_paid_usd': total_paid_usd,
        'total_paid_this_year_usd': total_paid_this_year_usd,
        'last_payment': last_payment,
        'camera_reports_count': camera_reports_submitted_qs.count(),
        'camera_reports_month': camera_reports_submitted_qs.filter(date__gte=month_start, date__lte=today).count(),
        'camera_total_vehicles': camera_reports_submitted_qs.aggregate(total=Sum('total_vehicles'))['total'] or 0,
        'camera_month_vehicles': camera_reports_submitted_qs.filter(
            date__gte=month_start,
            date__lte=today,
        ).aggregate(total=Sum('total_vehicles'))['total'] or 0,
        'camera_total_screenshots': camera_reports_qs.aggregate(total=Sum('screenshots_count'))['total'] or 0,
        'latest_camera_report': camera_reports_submitted_qs.order_by('-date', '-submitted_at').first(),
    }
    return render(request, 'admin/site_employee_portal.html', context)


@login_required
@no_cache_view
def admin_add_site_employee(request, site_id):
    """
    Ajouter un membre d'équipe pour un site.
    """
    user = request.user
    ensure_superuser_admin_profile(user)
    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    next_url = _safe_next_url(request) or ""
    requested_role = (request.GET.get("role") or request.POST.get("role") or "").strip()
    if requested_role not in {UserProfile.EMPLOYEE_ROLE, UserProfile.CAMERA_CONTROLLER_ROLE}:
        requested_role = UserProfile.EMPLOYEE_ROLE
    creation_mode_label = "contrôleur caméra" if requested_role == UserProfile.CAMERA_CONTROLLER_ROLE else "membre"

    if request.method == 'POST':
        form = SiteEmployeeForm(request.POST, request.FILES, initial_role=requested_role)
        if form.is_valid():
            profile = form.save(site=site)
            employee_name = profile.user.get_full_name() or profile.user.username
            AuditLog.log(
                user=user,
                action="CREER",
                description=f"Compte équipe ajouté sur {site.nom}: {employee_name} ({profile.get_role_display()})",
                content_object=profile,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )
            messages.success(request, f'Compte "{employee_name}" ajouté avec succès.')
            return redirect(next_url or reverse('admin_site_employees', kwargs={'site_id': site.id}))
    else:
        form = SiteEmployeeForm(initial={"role": requested_role}, initial_role=requested_role)

    return render(request, 'admin/site_employee_form.html', {
        'site': site,
        'form': form,
        'mode': 'create',
        'next_url': next_url,
        'requested_role': requested_role,
        'creation_mode_label': creation_mode_label,
    })


@login_required
@no_cache_view
def admin_edit_site_employee(request, site_id, profile_id):
    """
    Modifier les informations d'un membre rattaché à un site.
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
        role__in=UserProfile.SITE_STAFF_ROLES,
    )

    if request.method == 'POST':
        form = SiteEmployeeForm(
            request.POST,
            request.FILES,
            user_instance=profile.user,
            profile_instance=profile,
        )
        if form.is_valid():
            updated_profile = form.save(site=site)
            employee_name = updated_profile.user.get_full_name() or updated_profile.user.username
            AuditLog.log(
                user=user,
                action="MODIFIER",
                description=f"Compte équipe modifié sur {site.nom}: {employee_name} ({updated_profile.get_role_display()})",
                content_object=updated_profile,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )
            messages.success(request, f'Informations de "{employee_name}" mises à jour.')
            return redirect('admin_site_employees', site_id=site.id)
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
    Retirer un membre d'équipe d'un site (désactivation du compte).
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
        role__in=UserProfile.SITE_STAFF_ROLES,
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
            description=f"Compte équipe retiré du site {site.nom}: {employee_name} ({profile.get_role_display()})",
            content_object=profile,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        messages.success(request, f'"{employee_name}" a été retiré du site et désactivé.')
        return redirect('admin_site_employees', site_id=site.id)

    return render(request, 'admin/site_employee_delete.html', {
        'site': site,
        'employee_profile': profile,
    })


@login_required
@no_cache_view
def admin_create_employee_payment(request, site_id, profile_id):
    """
    Enregistrer un paiement équipe puis générer une fiche de paiement.
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
        role__in=UserProfile.SITE_STAFF_ROLES,
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
    share_meta = _build_payment_receipt_share_meta(request, payment)

    context = {
        'site': site,
        'payment': payment,
        'company_name': "Shine Congo",
        'is_shared_view': False,
        **share_meta,
    }
    return render(request, 'admin/payment_receipt.html', context)


@login_required
@no_cache_view
def admin_employee_payment_receipt_pdf(request, site_id, payment_id):
    """
    Génère la fiche de paiement en PDF pour téléchargement ou partage.
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
    return _build_payment_receipt_pdf_response(payment, download=request.GET.get("download") == "1")


@no_cache_view
def shared_employee_payment_receipt(request, token):
    """
    Afficher une fiche de paiement via un lien signé, sans connexion.
    """
    payment = _get_shared_payment_from_token(token)
    share_meta = _build_payment_receipt_share_meta(request, payment)

    context = {
        'site': payment.site,
        'payment': payment,
        'company_name': "Shine Congo",
        'is_shared_view': True,
        **share_meta,
    }
    return render(request, 'admin/payment_receipt.html', context)


@no_cache_view
def shared_employee_payment_receipt_pdf(request, token):
    """
    Sert la version PDF d'une fiche de paiement via lien signé.
    """
    payment = _get_shared_payment_from_token(token)
    return _build_payment_receipt_pdf_response(payment, download=request.GET.get("download") == "1")


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
def admin_edit_site_document(request, site_id, document_id):
    """
    Renommer un document déjà présent dans la bibliothèque du site.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    document = get_object_or_404(SiteDocument, id=document_id, site=site)
    next_url = _safe_next_url(request) or reverse('admin_site_documents', args=[site.id])

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        next_url = _safe_next_url(request) or reverse('admin_site_documents', args=[site.id])

        if not title:
            messages.error(request, "Le nom du document est requis.")
        elif title == document.title:
            messages.info(request, "Aucune modification détectée sur le nom du document.")
            return redirect(next_url)
        else:
            old_title = document.title
            document.title = title
            document.save(update_fields=['title', 'updated_at'])

            AuditLog.log(
                user=user,
                action="MODIFIER",
                description=f"Document renommé pour le site {site.nom}: {old_title} → {title}",
                content_object=document,
                donnees_avant={'title': old_title},
                donnees_apres={'title': title},
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            messages.success(request, f'Document renommé avec succès: "{title}".')
            return redirect(next_url)

    return render(request, 'admin/edit_site_document.html', {
        'site': site,
        'document': document,
        'next_url': next_url,
    })


@login_required
@no_cache_view
def admin_move_site_document(request, site_id, document_id):
    """
    Migrer un document d'une section documentaire vers une autre.
    """
    user = request.user
    ensure_superuser_admin_profile(user)

    if not is_admin_user(user):
        messages.error(request, "Accès refusé. Cette page est réservée aux administrateurs.")
        return redirect('dashboard')

    site = get_object_or_404(Location, id=site_id)
    document = get_object_or_404(SiteDocument, id=document_id, site=site)
    next_url = _safe_next_url(request) or reverse('admin_site_documents', args=[site.id])

    if request.method == 'POST':
        form = SiteDocumentMoveForm(request.POST, document_instance=document)
        if form.is_valid():
            target_file_type = form.cleaned_data['file_type']
            if target_file_type == document.file_type:
                messages.info(request, "Ce document est déjà classé dans cette section.")
                return redirect(next_url)

            previous_file_type = document.file_type
            previous_label = document.get_file_type_display()
            moved_document = form.save(document)
            destination_url = (
                f"{reverse('admin_site_documents', args=[site.id])}"
                f"?type={moved_document.file_type}#document-{moved_document.id}"
            )

            AuditLog.log(
                user=user,
                action="MODIFIER",
                description=(
                    f"Document migré pour le site {site.nom}: "
                    f"{moved_document.title} ({previous_label} → {moved_document.get_file_type_display()})"
                ),
                content_object=moved_document,
                donnees_avant={
                    'file_type': previous_file_type,
                    'file_type_label': previous_label,
                },
                donnees_apres={
                    'file_type': moved_document.file_type,
                    'file_type_label': moved_document.get_file_type_display(),
                },
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
            )

            messages.success(
                request,
                f'Document migré avec succès vers la section "{moved_document.get_file_type_display()}".',
            )
            return redirect(destination_url)
    else:
        form = SiteDocumentMoveForm(document_instance=document)

    return render(request, 'admin/move_site_document.html', {
        'site': site,
        'document': document,
        'form': form,
        'next_url': next_url,
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
