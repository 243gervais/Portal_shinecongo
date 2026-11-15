"""Bounded, read-only site dashboard; detailed legacy ledgers stay available separately."""
from datetime import datetime, time, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.db.models import Count, Prefetch, Q, Sum
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from comptes.pagination import paginate_queryset
from lavages.models import CarWash, CarWashPhoto
from pointage.models import ShiftDay
from problemes.models import IssueReport
from sites.models import DailyBankDeposit, SiteDocument, SiteJournalEntry, SiteLossEntry


def dashboard_period(request, today):
    def read_date(name):
        try:
            return parse_date(request.GET.get(name, ''))
        except ValueError:
            return None
    start = read_date('date_debut')
    end = read_date('date_fin')
    if request.GET.get('filter_today') == 'true' or not (start or end):
        return today, today
    end = min(end or today, today)
    start = min(start or end.replace(day=1), today)
    return (end, start) if start > end else (start, end)


def dashboard_context(request, site):
    from comptes.views import _build_site_attendance_rows

    today = timezone.localdate()
    start, end = dashboard_period(request, today)
    period = {'date__range': (start, end)}
    start_at = timezone.make_aware(datetime.combine(start, time.min))
    end_at = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min))
    washes = CarWash.objects.filter(site=site, **period)
    deposits = DailyBankDeposit.objects.filter(site=site, **period)
    losses = SiteLossEntry.objects.filter(site=site, **period)
    reports = ShiftDay.objects.filter(site=site, daily_report_confirmed=True, **period)
    wash_totals = washes.aggregate(amount=Sum('montant', default=Decimal('0')), count=Count('pk'))
    bank = deposits.aggregate(amount=Sum('amount', default=Decimal('0')), count=Count('pk'))
    expenses = losses.aggregate(
        total=Sum('amount', default=Decimal('0')),
        cash=Sum('amount', filter=Q(funding_source='CAISSE'), default=Decimal('0')),
        bank=Sum('amount', filter=Q(funding_source='BANQUE'), default=Decimal('0')),
    )
    report_totals = reports.aggregate(amount=Sum('total_amount_reported_fc', default=Decimal('0')), count=Count('pk'))
    open_issues = IssueReport.objects.filter(site=site, statut__in=['OUVERT', 'EN_COURS'])
    issue_count = open_issues.count()
    tab = request.GET.get('tab', 'overview')
    if tab not in {'overview', 'washes', 'finance', 'issues', 'photos'}:
        tab = 'overview'
    base_url = reverse('admin_site_detail', args=[site.pk])
    date_params = {'date_debut': start.isoformat(), 'date_fin': end.isoformat()}

    def tab_url(name):
        return f'{base_url}?{urlencode({**date_params, "tab": name})}'

    context = {
        'site': site, 'today': today, 'start': start, 'end': end, 'tab': tab,
        'date_debut': start.isoformat(), 'date_fin': end.isoformat(), 'detail_date': end,
        'tabs': [{'key': key, 'label': label, 'url': tab_url(key)} for key, label in [
            ('overview', 'Vue d’ensemble'), ('washes', 'Lavages'), ('finance', 'Finances'),
            ('issues', 'Problèmes'), ('photos', 'Photos'),
        ]],
        'presets': [{'label': label, 'url': f'{base_url}?{urlencode({"date_debut": first.isoformat(), "date_fin": last.isoformat(), "tab": tab})}'}
                    for label, first, last in [
                        ("Aujourd’hui", today, today), ('Hier', today - timedelta(days=1), today - timedelta(days=1)),
                        ('Cette semaine', today - timedelta(days=today.weekday()), today),
                        ('Ce mois', today.replace(day=1), today),
                    ]],
        'washes_url': tab_url('washes'), 'finance_url': tab_url('finance'),
        'issues_url': tab_url('issues'), 'photos_url': tab_url('photos'),
        'records_url': f'{base_url}?{urlencode({**date_params, "view": "records"})}',
        'chiffre_periode': wash_totals['amount'], 'total_lavages': wash_totals['count'],
        'deposits_total': bank['amount'], 'deposit_count': bank['count'],
        'cash_expenses': expenses['cash'], 'bank_expenses': expenses['bank'],
        'expenses_total': expenses['total'], 'bank_net': bank['amount'] - expenses['bank'],
        'cash_balance': wash_totals['amount'] - bank['amount'] - expenses['cash'],
        'report_total': report_totals['amount'], 'report_count': report_totals['count'],
        'report_variance': report_totals['amount'] - wash_totals['amount'],
        'open_issue_count': issue_count,
    }
    wash_rows = washes.select_related('employe').annotate(photo_count_value=Count('photos')).order_by('-date', '-created_at', '-pk')
    wash_search = (request.GET.get('q') or '').strip()[:120]
    context['wash_search'] = wash_search
    if tab == 'washes' and wash_search:
        wash_rows = wash_rows.filter(Q(plaque__icontains=wash_search) | Q(employe__first_name__icontains=wash_search)
                                     | Q(employe__last_name__icontains=wash_search) | Q(employe__username__icontains=wash_search))
    if tab in {'overview', 'washes'}:
        # One preview per wash, using a per-parent windowed prefetch rather than all photos.
        wash_rows = wash_rows.prefetch_related(Prefetch('photos', queryset=CarWashPhoto.objects.order_by('-uploaded_at', '-pk')[:1], to_attr='dashboard_photos'))
        context['wash_page'] = paginate_queryset(request, wash_rows, per_page=20, page_param='washes_page') if tab == 'washes' else None
        context['recent_washes'] = list(wash_rows[:6]) if tab == 'overview' else context['wash_page']
    if tab == 'overview':
        week_start = end - timedelta(days=end.weekday())
        week_end = min(week_start + timedelta(days=6), today)
        context['selected_single_date'] = start if start == end else None
        context['week_start'] = week_start
        context['week_end'] = week_end
        context['chiffre_week'] = CarWash.objects.filter(site=site, date__range=(week_start, week_end)).aggregate(total=Sum('montant', default=Decimal('0')))['total']
        context['attendance'] = _build_site_attendance_rows(site, end)
        context['recent_journal_entries'] = list(SiteJournalEntry.objects.filter(site=site).select_related('created_by').order_by('-entry_date', '-pk')[:3])
        context['documents_count'] = SiteDocument.objects.filter(site=site).count()
        context['recent_reports'] = list(reports.select_related('employe').order_by('-date', '-updated_at', '-pk')[:4])
    elif tab == 'finance':
        context['deposits_page'] = paginate_queryset(request, deposits.select_related('created_by').order_by('-date', '-pk'), per_page=15, page_param='deposits_page')
        context['losses_page'] = paginate_queryset(request, losses.select_related('created_by').order_by('-date', '-pk'), per_page=15, page_param='losses_page')
    elif tab == 'issues':
        status = request.GET.get('status', 'open')
        issues = IssueReport.objects.filter(site=site)
        if status == 'period':
            issues = issues.filter(created_at__gte=start_at, created_at__lt=end_at)
        else:
            status = 'open'
            issues = open_issues
        context['issue_status'] = status
        context['issues_page'] = paginate_queryset(request, issues.select_related('employe', 'traite_par').order_by('-created_at', '-pk'), per_page=15, page_param='issues_page')
    elif tab == 'photos':
        photos = CarWashPhoto.objects.filter(lavage__site=site, lavage__date__range=(start, end)).select_related('lavage', 'lavage__employe').order_by('-lavage__date', '-uploaded_at', '-pk')
        context['photos_page'] = paginate_queryset(request, photos, per_page=24, page_param='photos_page')
    return context


def render_site_dashboard(request, site):
    return render(request, 'admin/site_dashboard.html', dashboard_context(request, site))
