from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog
from comptes.pagination import paginate_queryset

from .forms import (
    ContractForm,
    CorporateCompanyForm,
    GenerateScheduleForm,
    RecurringScheduleForm,
    VehicleForm,
    WorkOrderFieldForm,
    WorkOrderManagerForm,
    WorkOrderProofPhotoForm,
    WorkOrderVehicleFormSet,
)
from .models import Contract, CorporateCompany, RecurringSchedule, Vehicle, WorkOrder, WorkOrderVehicle
from .permissions import is_mobile_admin, is_mobile_manager, manager_required, mobile_login_required
from .services import build_service_receipt_pdf, generate_work_orders_for_range


def _can_view_work_order(user, work_order):
    return is_mobile_manager(user) or work_order.assigned_employees.filter(pk=user.pk).exists()


def _status_counts():
    return dict(WorkOrder.objects.values_list("status").annotate(total=Count("id")))


@manager_required
def dashboard(request):
    today = timezone.localdate()
    week_end = today + timedelta(days=6)
    month_start = today.replace(day=1)
    completed_month = WorkOrder.objects.filter(status=WorkOrder.STATUS_COMPLETED, scheduled_start__date__gte=month_start)
    revenue = completed_month.aggregate(total=Sum("vehicle_lines__billable_amount"))["total"] or Decimal("0.00")
    direct_cost = sum((wo.direct_cost_amount for wo in completed_month), Decimal("0.00"))
    context = {
        "active_contracts": Contract.objects.filter(status="ACTIVE").count(),
        "contracted_monthly_revenue": Contract.objects.filter(status="ACTIVE").aggregate(total=Sum("monthly_package_price"))["total"] or Decimal("0.00"),
        "today_visits": WorkOrder.objects.filter(scheduled_start__date=today).count(),
        "week_visits": WorkOrder.objects.filter(scheduled_start__date__range=(today, week_end)).count(),
        "status_counts": _status_counts(),
        "completed_washes_month": WorkOrderVehicle.objects.filter(
            status=WorkOrderVehicle.STATUS_COMPLETED,
            work_order__scheduled_start__date__gte=month_start,
        ).count(),
        "unconfirmed_orders": WorkOrder.objects.filter(
            status__in=[WorkOrder.STATUS_AWAITING_CONFIRMATION, WorkOrder.STATUS_SUBMITTED],
        ).filter(Q(client_confirmed_at__isnull=True) | Q(associate_confirmed_at__isnull=True)).count(),
        "direct_expenses_month": direct_cost,
        "estimated_margin": revenue - direct_cost,
        "recent_work_orders": WorkOrder.objects.select_related("company", "contract").order_by("-updated_at")[:8],
        "can_view_financials": is_mobile_manager(request.user),
    }
    return render(request, "mobilewash/dashboard.html", context)


@manager_required
def companies(request):
    query = request.GET.get("q", "").strip()
    queryset = CorporateCompany.objects.all().annotate(
        active_contract_count=Count("contracts", filter=Q(contracts__status="ACTIVE")),
        vehicle_count=Count("vehicles", filter=Q(vehicles__is_active=True)),
    )
    if query:
        queryset = queryset.filter(Q(legal_name__icontains=query) | Q(trading_name__icontains=query) | Q(telephone__icontains=query))
    page_obj = paginate_queryset(request, queryset, per_page=20)
    return render(request, "mobilewash/company_list.html", {"page_obj": page_obj, "query": query})


@manager_required
@require_http_methods(["GET", "POST"])
def company_create(request):
    form = CorporateCompanyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        company = form.save()
        AuditLog.log(request.user, "CREER", "Entreprise corporate creee", content_object=company)
        messages.success(request, "Entreprise creee.")
        return redirect("mobilewash_company_detail", company_id=company.id)
    return render(request, "mobilewash/form.html", {"form": form, "title": "Nouvelle entreprise"})


@manager_required
def company_detail(request, company_id):
    company = get_object_or_404(CorporateCompany, pk=company_id)
    contracts = company.contracts.all()
    work_orders = company.work_orders.select_related("contract").order_by("-scheduled_start")[:12]
    vehicles = company.vehicles.all()[:20]
    completed = company.work_orders.filter(status=WorkOrder.STATUS_COMPLETED)
    revenue = WorkOrderVehicle.objects.filter(work_order__in=completed).aggregate(total=Sum("billable_amount"))["total"] or Decimal("0.00")
    direct_cost = sum((wo.direct_cost_amount for wo in completed), Decimal("0.00"))
    return render(
        request,
        "mobilewash/company_detail.html",
        {
            "company": company,
            "contracts": contracts,
            "work_orders": work_orders,
            "vehicles": vehicles,
            "revenue": revenue,
            "direct_cost": direct_cost,
            "margin": revenue - direct_cost,
        },
    )


@manager_required
@require_http_methods(["GET", "POST"])
def contract_form(request, contract_id=None):
    instance = get_object_or_404(Contract, pk=contract_id) if contract_id else None
    before = {"status": instance.status, "monthly_package_price": str(instance.monthly_package_price)} if instance else None
    form = ContractForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        contract = form.save(commit=False)
        if not contract.created_by_id:
            contract.created_by = request.user
        if contract.status == "ACTIVE" and not contract.approved_by_id:
            contract.approved_by = request.user
        contract.save()
        form.save_m2m()
        after = {"status": contract.status, "monthly_package_price": str(contract.monthly_package_price)}
        AuditLog.log(request.user, "MODIFIER" if instance else "CREER", "Contrat mobile enregistre", content_object=contract, donnees_avant=before, donnees_apres=after)
        messages.success(request, "Contrat enregistre.")
        return redirect("mobilewash_contract_detail", contract_id=contract.id)
    return render(request, "mobilewash/form.html", {"form": form, "title": "Contrat mobile"})


@manager_required
def contracts(request):
    queryset = Contract.objects.select_related("company").order_by("-start_date")
    status = request.GET.get("status", "")
    if status:
        queryset = queryset.filter(status=status)
    page_obj = paginate_queryset(request, queryset, per_page=20)
    return render(request, "mobilewash/contract_list.html", {"page_obj": page_obj, "status": status})


@manager_required
def contract_detail(request, contract_id):
    contract = get_object_or_404(Contract.objects.select_related("company"), pk=contract_id)
    today = timezone.localdate()
    usage = contract.usage_for_period(today.replace(day=1), today)
    return render(
        request,
        "mobilewash/contract_detail.html",
        {
            "contract": contract,
            "usage": usage,
            "schedules": contract.schedules.all(),
            "work_orders": contract.work_orders.order_by("-scheduled_start")[:12],
        },
    )


@manager_required
@require_http_methods(["GET", "POST"])
def vehicle_form(request, vehicle_id=None):
    instance = get_object_or_404(Vehicle, pk=vehicle_id) if vehicle_id else None
    form = VehicleForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        vehicle = form.save()
        AuditLog.log(request.user, "MODIFIER" if instance else "CREER", "Vehicule corporate enregistre", content_object=vehicle)
        messages.success(request, "Vehicule enregistre.")
        return redirect("mobilewash_company_detail", company_id=vehicle.company_id)
    return render(request, "mobilewash/form.html", {"form": form, "title": "Vehicule corporate"})


@manager_required
def vehicles(request):
    queryset = Vehicle.objects.select_related("company").order_by("company__legal_name", "license_plate")
    page_obj = paginate_queryset(request, queryset, per_page=30)
    return render(request, "mobilewash/vehicle_list.html", {"page_obj": page_obj})


@manager_required
@require_http_methods(["GET", "POST"])
def schedule_form(request, schedule_id=None):
    instance = get_object_or_404(RecurringSchedule, pk=schedule_id) if schedule_id else None
    form = RecurringScheduleForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        schedule = form.save()
        AuditLog.log(request.user, "MODIFIER" if instance else "CREER", "Programme recurrent mobile enregistre", content_object=schedule)
        messages.success(request, "Programme enregistre.")
        return redirect("mobilewash_schedules")
    return render(request, "mobilewash/form.html", {"form": form, "title": "Programme recurrent"})


@manager_required
def schedules(request):
    queryset = RecurringSchedule.objects.select_related("company", "contract").order_by("weekday", "planned_start_time")
    page_obj = paginate_queryset(request, queryset, per_page=20)
    generate_form = GenerateScheduleForm(initial={"date_from": timezone.localdate(), "date_to": timezone.localdate() + timedelta(days=14)})
    return render(request, "mobilewash/schedule_list.html", {"page_obj": page_obj, "generate_form": generate_form})


@manager_required
@require_http_methods(["POST"])
def generate_schedule(request):
    form = GenerateScheduleForm(request.POST)
    if form.is_valid():
        created = generate_work_orders_for_range(form.cleaned_data["date_from"], form.cleaned_data["date_to"], created_by=request.user)
        messages.success(request, f"{len(created)} ordre(s) de travail genere(s). Les doublons existants ont ete ignores.")
    else:
        messages.error(request, "Periode invalide.")
    return redirect("mobilewash_schedules")


@mobile_login_required
def work_orders(request):
    queryset = WorkOrder.objects.select_related("company", "contract", "team_leader").prefetch_related("assigned_employees")
    if not is_mobile_manager(request.user):
        queryset = queryset.filter(assigned_employees=request.user)
    status = request.GET.get("status", "")
    if status:
        queryset = queryset.filter(status=status)
    page_obj = paginate_queryset(request, queryset.order_by("-scheduled_start"), per_page=25)
    return render(request, "mobilewash/work_order_list.html", {"page_obj": page_obj, "status": status, "is_manager": is_mobile_manager(request.user)})


@manager_required
@require_http_methods(["GET", "POST"])
def work_order_form(request, work_order_id=None):
    instance = get_object_or_404(WorkOrder, pk=work_order_id) if work_order_id else None
    form = WorkOrderManagerForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        work_order = form.save(commit=False)
        if not work_order.created_by_id:
            work_order.created_by = request.user
        work_order.save()
        form.save_m2m()
        work_order.create_number()
        AuditLog.log(request.user, "MODIFIER" if instance else "CREER", "Ordre de travail mobile enregistre", content_object=work_order)
        messages.success(request, "Ordre de travail enregistre.")
        return redirect("mobilewash_work_order_detail", work_order_id=work_order.id)
    return render(request, "mobilewash/form.html", {"form": form, "title": "Ordre de travail mobile"})


@mobile_login_required
def work_order_detail(request, work_order_id):
    work_order = get_object_or_404(WorkOrder.objects.select_related("company", "contract", "schedule"), pk=work_order_id)
    if not _can_view_work_order(request.user, work_order):
        raise PermissionDenied
    return render(request, "mobilewash/work_order_detail.html", {"work_order": work_order, "is_manager": is_mobile_manager(request.user)})


@mobile_login_required
@require_http_methods(["GET", "POST"])
def field_work_order(request, work_order_id):
    work_order = get_object_or_404(WorkOrder, pk=work_order_id)
    if not is_mobile_manager(request.user) and not work_order.can_field_user_edit(request.user):
        raise PermissionDenied
    form = WorkOrderFieldForm(request.POST or None, request.FILES or None, instance=work_order)
    formset = WorkOrderVehicleFormSet(request.POST or None, request.FILES or None, instance=work_order)
    photo_form = WorkOrderProofPhotoForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            updated_order = form.save(commit=False)
            updated_order.status = WorkOrder.STATUS_SUBMITTED
            now = timezone.now()
            updated_order.associate_confirmed_at = updated_order.associate_confirmed_at or now
            updated_order.client_confirmed_at = updated_order.client_confirmed_at or now
            updated_order.save()
            formset.save()
            if photo_form.is_valid() and photo_form.cleaned_data.get("photo"):
                photo = photo_form.save(commit=False)
                photo.work_order = updated_order
                photo.uploaded_by = request.user
                photo.save()
            AuditLog.log(request.user, "CHANGER_STATUT", "Ordre mobile soumis par le terrain", content_object=updated_order)
        messages.success(request, "Intervention soumise pour revue manager.")
        return redirect("mobilewash_work_order_detail", work_order_id=work_order.id)
    return render(
        request,
        "mobilewash/field_work_order.html",
        {"work_order": work_order, "form": form, "formset": formset, "photo_form": photo_form},
    )


@manager_required
@require_http_methods(["POST"])
def review_work_order(request, work_order_id):
    work_order = get_object_or_404(WorkOrder, pk=work_order_id)
    action = request.POST.get("action")
    try:
        if action == "complete":
            work_order.reviewed_by = request.user
            work_order.reviewed_at = timezone.now()
            work_order.approve_completion(request.user, override_review=is_mobile_admin(request.user))
            messages.success(request, "Ordre de travail termine.")
        elif action == "reopen":
            before = {"status": work_order.status}
            work_order.status = WorkOrder.STATUS_IN_PROGRESS
            work_order.reviewed_by = None
            work_order.reviewed_at = None
            work_order.completed_at = None
            work_order.save()
            AuditLog.log(request.user, "CHANGER_STATUT", "Ordre mobile rouvert", content_object=work_order, donnees_avant=before, donnees_apres={"status": work_order.status})
            messages.success(request, "Ordre rouvert.")
    except ValidationError as exc:
        messages.error(request, "; ".join([str(v) for v in exc.message_dict.values()]) if hasattr(exc, "message_dict") else str(exc))
    return redirect("mobilewash_work_order_detail", work_order_id=work_order.id)


@mobile_login_required
def service_receipt_pdf(request, work_order_id):
    work_order = get_object_or_404(WorkOrder.objects.select_related("company", "contract"), pk=work_order_id)
    if not _can_view_work_order(request.user, work_order):
        raise PermissionDenied
    pdf_buffer = build_service_receipt_pdf(work_order)
    filename = f"{work_order.work_order_number or work_order.pk}-recu-service.pdf"
    return FileResponse(pdf_buffer, as_attachment=False, filename=filename, content_type="application/pdf")

