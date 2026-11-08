import calendar
from datetime import timedelta

from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from comptes.models import UserProfile
from pointage.attendance import attendance_schedule_context, get_clock_in_status, shift_start_datetime
from pointage.models import ShiftDay


def _worked_seconds(shift):
    if not shift or not shift.clock_in_time or not shift.clock_out_time:
        return 0
    return max(0, int((shift.clock_out_time - shift.clock_in_time).total_seconds()))


def _duration_label(seconds):
    hours, minutes = divmod(seconds // 60, 60)
    return f'{hours}h{minutes:02d}'


def month_register(site, reference_date, *, employee_id=None):
    # Reuse the portal's existing attribution and duration rules.
    from comptes.views import _build_pointage_attribution_context

    today = timezone.localdate()
    first = reference_date.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    shifts = list(ShiftDay.objects.filter(site=site, date__range=(first, min(last, today)))
                  .select_related('employe', 'corrected_by').order_by('date', 'pk'))
    historical_ids = {shift.employe_id for shift in shifts}
    profile_filter = (
        Q(site=site, actif=True, user__is_active=True,
          role__in=[UserProfile.EMPLOYEE_ROLE, UserProfile.MANAGER_ROLE])
        | Q(user_id__in=historical_ids)
    )
    if employee_id:
        profile_filter |= Q(site=site, user_id=employee_id, role__in=[UserProfile.EMPLOYEE_ROLE, UserProfile.MANAGER_ROLE])
        profile_filter |= Q(user_id=employee_id, user_id__in=ShiftDay.objects.filter(site=site).values('employe_id'))
    profiles = list(UserProfile.objects.filter(profile_filter).select_related('user')
                    .order_by('user__first_name', 'user__last_name', 'user__username'))
    active = [profile for profile in profiles if profile.site_id == site.id and profile.actif and profile.user.is_active]
    active_ids = {profile.user_id for profile in active}
    attribution = _build_pointage_attribution_context(site, active)
    aliases = attribution['alias_by_user_id']
    by_day = {}
    for shift in shifts:
        canonical = aliases.get(shift.employe_id, shift.employe_id)
        key = (canonical, shift.date)
        if key not in by_day or shift.employe_id == canonical:
            by_day[key] = shift
    canonical_id = aliases.get(employee_id, employee_id)
    visible = [profile for profile in profiles if profile.user_id not in aliases]
    if employee_id:
        visible = [profile for profile in visible if profile.user_id == canonical_id]
        if not visible:
            raise Http404('Employe introuvable pour ce site et cette periode.')

    rows = []
    for profile in visible:
        days = []
        worked_seconds = 0
        present = late = absent = missing_end = late_minutes = 0
        is_current = profile.user_id in active_ids
        hired_on = profile.date_embauche or timezone.localtime(profile.user.date_joined).date()
        for offset in range(last.day):
            day = first + timedelta(days=offset)
            shift = by_day.get((profile.user_id, day))
            minutes = 0
            if day > today:
                status = {'code': 'FUTURE', 'label': 'À venir'}
            elif shift and shift.clock_in_time:
                status = shift.get_clock_in_attendance_status()
                present += 1
                if status['code'] == 'LATE':
                    late += 1
                    minutes = max(0, int((shift.clock_in_time - shift_start_datetime(day)).total_seconds() // 60))
                    late_minutes += minutes
                if not shift.clock_out_time:
                    missing_end += 1
                worked_seconds += _worked_seconds(shift)
            elif day.weekday() == 6:
                status = {'code': 'OFF', 'label': 'Repos'}
            elif not is_current or day < hired_on:
                # No departure/start-date history exists: never infer absences for former staff.
                status = {'code': 'UNRECORDED', 'label': 'Non renseigné'}
            else:
                status = get_clock_in_status(day)
                absent += int(status['code'] == 'ABSENT')
            days.append({
                'date': day, 'status': status, 'shift': shift, 'late_minutes': minutes,
                'duration': _duration_label(_worked_seconds(shift)) if shift and shift.clock_out_time else '',
            })
        rows.append({
            'profile': profile, 'employee': profile.user, 'days': days, 'present': present,
            'late': late, 'on_time': present - late, 'absent': absent, 'missing_end': missing_end,
            'hours': _duration_label(worked_seconds), 'late_minutes': late_minutes,
            'punctuality': round((present - late) * 100 / present) if present else None,
            'archived': not is_current,
            'attributed_names': attribution['attributed_names_by_user_id'].get(profile.user_id, []),
        })
    return {
        'rows': rows, 'first': first, 'last': last, 'month_value': first.strftime('%Y-%m'),
        'previous_month': (first - timedelta(days=1)).strftime('%Y-%m') if first.year > 1 or first.month > 1 else first.strftime('%Y-%m'),
        'next_month': (last + timedelta(days=1)).strftime('%Y-%m'),
        'can_next': last < today.replace(day=1), 'schedule': attendance_schedule_context(),
        'leading_days': range(first.weekday()),
    }
