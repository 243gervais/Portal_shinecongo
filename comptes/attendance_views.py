from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from comptes.attendance_register import month_register
from comptes.views import _parse_payroll_month, ensure_superuser_admin_profile, is_admin_user, no_cache_view
from sites.models import Location


@login_required
@no_cache_view
def employee_attendance(request, site_id, employee_id):
    ensure_superuser_admin_profile(request.user)
    if not is_admin_user(request.user):
        return redirect('dashboard')
    site = get_object_or_404(Location, pk=site_id)
    today = timezone.localdate()
    month = min(_parse_payroll_month(request.GET.get('month'), today), today.replace(day=1))
    register = month_register(site, month, employee_id=employee_id)
    employee = register['rows'][0]
    status = request.GET.get('status', 'all')
    allowed = {'all', 'PRESENT', 'LATE', 'ABSENT', 'MISSING'}
    if status not in allowed:
        status = 'all'
    days = [day for day in employee['days'] if day['status']['code'] != 'FUTURE']
    if status == 'MISSING':
        days = [day for day in days if day['shift'] and day['shift'].clock_in_time and not day['shift'].clock_out_time]
    elif status != 'all':
        days = [day for day in days if day['status']['code'] == status]
    return render(request, 'admin/employee_attendance.html', {
        'site': site, 'register': register, 'record': employee, 'days': days,
        'selected_status': status, 'today': today,
    })
