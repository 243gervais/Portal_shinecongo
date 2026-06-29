from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditLog
from comptes.forms import get_water_purchase_default_amount
from comptes.models import UserProfile
from lavages.models import CarWash, CarWashPhoto
from pointage.models import ShiftDay
from pointage.report_sync import sync_site_finance_from_daily_reports
from pointage.utils import generate_qr_code_image, get_client_ip, get_user_agent
from pointage.views import (
    _build_initial_daily_expense_form,
    _parse_daily_expenses_form,
    _send_fuel_purchase_notification,
    _send_final_report_notification,
    _send_water_purchase_notification,
)
from pointage.views_manager import _parse_dashboard_date_range
from problemes.models import IssueReport
from problemes.views import _send_issue_report_notification
from sites.models import Location, SiteFuelPurchase, SiteWaterPurchase, get_default_water_supplier

from .pagination import PortalPagination
from .permissions import IsManagerOrAdmin, IsPortalEmployee
from .serializers import (
    EmployeeCarWashDetailSerializer,
    EmployeeCarWashSerializer,
    EmployeeFuelPurchaseSerializer,
    EmployeeIssueSerializer,
    EmployeeShiftHistorySerializer,
    EmployeeWaterPurchaseSerializer,
    ManagerCarWashSerializer,
    ManagerIssueSerializer,
    ShiftDaySerializer,
    SiteSummarySerializer,
)


PHOTO_PREFETCH = Prefetch(
    "photos",
    queryset=CarWashPhoto.objects.order_by("uploaded_at"),
    to_attr="prefetched_photos",
)


def _profile(user):
    return getattr(user, "userprofile", None)


def _user_role(user):
    if user.is_superuser:
        return UserProfile.ADMIN_ROLE
    profile = _profile(user)
    return profile.role if profile else ""


def _user_summary(user):
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.get_full_name() or user.username,
    }


def _fc_display(value):
    return f"{Decimal(value or 0):,.0f} FC".replace(",", " ")


def _employee_profile(user):
    profile = _profile(user)
    if not profile or not profile.is_employe() or not profile.site_id:
        return None
    return profile


def _manager_accessible_sites(user):
    qs = Location.objects.filter(actif=True).only(
        "id",
        "nom",
        "ville",
        "gps_actif",
        "rayon_autorisé_mètres",
        "site_token",
        "latitude",
        "longitude",
    )
    if user.is_superuser:
        return qs.order_by("nom")
    profile = _profile(user)
    if not profile:
        return Location.objects.none()
    if profile.is_admin():
        return qs.order_by("nom")
    if profile.is_manager() and profile.site_id:
        return qs.filter(id=profile.site_id).order_by("nom")
    return Location.objects.none()


def _site_options(qs):
    return [{"id": str(site.id), "nom": site.nom} for site in qs]


def _employee_options_for_sites(site_ids):
    queryset = (
        User.objects.filter(
            userprofile__site_id__in=site_ids,
            userprofile__role=UserProfile.EMPLOYEE_ROLE,
            userprofile__actif=True,
        )
        .order_by("first_name", "last_name", "username")
        .distinct()
    )
    return [
        {
            "id": employee.id,
            "nom": employee.get_full_name() or employee.username,
        }
        for employee in queryset
    ]


def _paginate(view, queryset, serializer_class, request, *, page_size=12, extra=None):
    paginator = PortalPagination()
    paginator.page_size = page_size
    page = paginator.paginate_queryset(queryset, request, view=view)
    serializer = serializer_class(page, many=True, context={"request": request})
    return paginator.get_paginated_response(serializer.data, extra=extra)


def _safe_employee_shift(shift):
    if not shift:
        return None
    serializer = EmployeeShiftHistorySerializer(shift)
    data = serializer.data
    data["submitted_total_amount"] = f"{Decimal(shift.total_amount_reported_fc or 0):.2f}"
    data["daily_expenses"] = [
        {
            "key": item["key"],
            "label": item["label"],
            "amount_fc": f"{item['amount_fc']:.2f}",
            "is_known": item["is_known"],
        }
        for item in shift.daily_expense_items
    ]
    return data


class PortalSessionApi(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = _user_role(user)
        profile = _profile(user)
        site = profile.site if profile and profile.site_id else None

        return Response(
            {
                "user": _user_summary(user),
                "role": role,
                "site": SiteSummarySerializer(site).data if site else None,
                "routes": {
                    "employee_home": "/employe/",
                    "manager_home": "/manager/",
                    "logout": "/logout/",
                },
            }
        )


class EmployeeDashboardApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        user = request.user
        profile = _employee_profile(user)
        today = timezone.localdate()
        shift_today = ShiftDay.objects.filter(employe=user, date=today).first()
        site = profile.site

        water_purchase_today = (
            SiteWaterPurchase.objects.filter(site=site, purchase_date=today)
            .select_related("supplier", "created_by")
            .order_by("-created_at")
            .first()
        )
        fuel_purchase_today = (
            SiteFuelPurchase.objects.filter(site=site, purchase_date=today)
            .select_related("created_by")
            .order_by("-created_at")
            .first()
        )

        return Response(
            {
                "today": today.isoformat(),
                "site": SiteSummarySerializer(site).data,
                "stats": {
                    "lavages_today": user.lavages.filter(date=today).count(),
                    "problemes_ouverts": user.problemes_signales.filter(statut="OUVERT").count(),
                    "rapport_envoye": bool(shift_today and shift_today.daily_report_confirmed),
                    "eau_signalee": bool(water_purchase_today),
                    "carburant_signale": bool(fuel_purchase_today),
                    "signalements_eau_mois": SiteWaterPurchase.objects.filter(
                        site=site,
                        billing_month=today.replace(day=1),
                    ).count(),
                    "signalements_carburant_mois": SiteFuelPurchase.objects.filter(
                        site=site,
                        billing_month=today.replace(day=1),
                    ).count(),
                },
                "shift_today": _safe_employee_shift(shift_today),
                "water_purchase_today": (
                    EmployeeWaterPurchaseSerializer(water_purchase_today).data
                    if water_purchase_today else None
                ),
                "fuel_purchase_today": (
                    EmployeeFuelPurchaseSerializer(fuel_purchase_today).data
                    if fuel_purchase_today else None
                ),
            }
        )


class EmployeePointageStatusApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        profile = _employee_profile(request.user)
        today = timezone.localdate()
        shift_today = ShiftDay.objects.filter(employe=request.user, date=today).first()

        return Response(
            {
                "today": today.isoformat(),
                "site": SiteSummarySerializer(profile.site).data,
                "site_token_prefill": request.query_params.get("site_token", "").strip(),
                "shift_today": _safe_employee_shift(shift_today),
                "can_clock_in": not bool(shift_today and shift_today.clock_in_time),
                "can_clock_out": bool(shift_today and shift_today.clock_in_time and not shift_today.clock_out_time),
            }
        )


class EmployeeClockInApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def post(self, request):
        user = request.user
        today = timezone.localdate()
        profile = _employee_profile(user)
        site_token = str(request.data.get("site_token", "")).strip()
        if not site_token:
            return Response({"message": "QR code requis."}, status=status.HTTP_400_BAD_REQUEST)

        existing_shift = ShiftDay.objects.filter(employe=user, date=today).first()
        if existing_shift and existing_shift.clock_in_time:
            return Response(
                {
                    "message": f"Vous avez déjà pointé l'entrée aujourd'hui à {timezone.localtime(existing_shift.clock_in_time):%H:%M}.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        site = get_object_or_404(Location, site_token=site_token, actif=True)
        if profile.site_id != site.id:
            return Response({"message": "Ce QR ne correspond pas à votre site."}, status=status.HTTP_400_BAD_REQUEST)

        gps_lat = request.data.get("gps_latitude")
        gps_lon = request.data.get("gps_longitude")
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
                        gps_status = "OK" if distance <= site.rayon_autorisé_mètres else "HORS_ZONE"
            except (ArithmeticError, InvalidOperation, TypeError, ValueError):
                lat = None
                lon = None

        shift = existing_shift or ShiftDay.objects.create(employe=user, site=site, date=today)
        shift.clock_in_time = timezone.now()
        if lat is not None and lon is not None:
            shift.clock_in_gps_latitude = lat
            shift.clock_in_gps_longitude = lon
            shift.clock_in_gps_distance_mètres = gps_distance
        shift.clock_in_gps_status = gps_status
        shift.save()

        AuditLog.log(
            user=user,
            action="AUTRE",
            description=f"Pointage entrée: {shift} (GPS: {gps_status})",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        return Response(
            {
                "message": "Pointage entrée enregistré avec succès.",
                "shift_today": _safe_employee_shift(shift),
            }
        )


class EmployeeClockOutApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def post(self, request):
        user = request.user
        today = timezone.localdate()
        profile = _employee_profile(user)
        site_token = str(request.data.get("site_token", "")).strip()
        if not site_token:
            return Response({"message": "QR code requis."}, status=status.HTTP_400_BAD_REQUEST)

        shift = ShiftDay.objects.filter(employe=user, date=today).first()
        if not shift or not shift.clock_in_time:
            return Response(
                {"message": "Impossible de pointer la sortie sans pointage d'entrée."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if shift.clock_out_time:
            return Response(
                {
                    "message": f"Vous avez déjà pointé la sortie à {timezone.localtime(shift.clock_out_time):%H:%M}.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        site = get_object_or_404(Location, site_token=site_token, actif=True)
        if profile.site_id != site.id:
            return Response({"message": "Ce QR ne correspond pas à votre site."}, status=status.HTTP_400_BAD_REQUEST)

        gps_lat = request.data.get("gps_latitude")
        gps_lon = request.data.get("gps_longitude")
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
                        gps_status = "OK" if distance <= site.rayon_autorisé_mètres else "HORS_ZONE"
            except (ArithmeticError, InvalidOperation, TypeError, ValueError):
                lat = None
                lon = None

        shift.clock_out_time = timezone.now()
        if lat is not None and lon is not None:
            shift.clock_out_gps_latitude = lat
            shift.clock_out_gps_longitude = lon
            shift.clock_out_gps_distance_mètres = gps_distance
        shift.clock_out_gps_status = gps_status
        shift.save()

        AuditLog.log(
            user=user,
            action="AUTRE",
            description=f"Pointage sortie: {shift} (GPS: {gps_status})",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        return Response(
            {
                "message": "Pointage sortie enregistré avec succès.",
                "shift_today": _safe_employee_shift(shift),
            }
        )


class EmployeeCarWashListCreateApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        queryset = (
            request.user.lavages.select_related("site")
            .annotate(photo_count_value=Count("photos", distinct=True))
            .prefetch_related(PHOTO_PREFETCH)
            .order_by("-created_at")
        )
        return _paginate(self, queryset, EmployeeCarWashSerializer, request, page_size=12)

    def post(self, request):
        profile = _employee_profile(request.user)
        type_service = str(request.data.get("type_service", "")).strip()
        plaque = str(request.data.get("plaque", "")).strip().upper()
        montant_raw = str(request.data.get("montant", "")).strip()
        notes = str(request.data.get("notes", "")).strip()
        plaque_photo = request.FILES.get("plaque_photo")
        photos = request.FILES.getlist("photos")

        valid_service_types = {choice[0] for choice in CarWash.TYPE_SERVICE_CHOICES}
        if type_service not in valid_service_types:
            return Response({"message": "Type de service invalide."}, status=status.HTTP_400_BAD_REQUEST)
        if not montant_raw:
            return Response({"message": "Le montant est requis."}, status=status.HTTP_400_BAD_REQUEST)
        if not photos:
            return Response({"message": "Au moins une photo est requise."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            montant_decimal = Decimal(montant_raw)
            if montant_decimal < 0:
                raise InvalidOperation
        except (ArithmeticError, InvalidOperation, TypeError, ValueError):
            return Response({"message": "Montant invalide."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            UserProfile.objects.select_for_update().filter(pk=profile.pk).first()
            duplicate_window_start = timezone.now() - timedelta(seconds=45)
            duplicate_qs = CarWash.objects.filter(
                employe=request.user,
                site=profile.site,
                date=timezone.localdate(),
                type_service=type_service,
                plaque=plaque,
                montant=montant_decimal,
                notes=notes,
                created_at__gte=duplicate_window_start,
            ).order_by("-created_at")

            for existing in duplicate_qs:
                if existing.photos.count() == len(photos):
                    return Response(
                        {"message": "Ce lavage vient déjà d'être enregistré. Le doublon a été bloqué."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            lavage = CarWash.objects.create(
                employe=request.user,
                site=profile.site,
                date=timezone.localdate(),
                type_service=type_service,
                plaque=plaque,
                plaque_photo=plaque_photo,
                montant=montant_decimal,
                notes=notes,
            )
            for photo in photos:
                CarWashPhoto.objects.create(lavage=lavage, photo=photo, type_photo="APRES")

        AuditLog.log(
            user=request.user,
            action="CREER",
            description=f"Nouveau lavage: {lavage}",
            content_object=lavage,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        sync_site_finance_from_daily_reports(profile.site, lavage.date, actor=request.user)

        lavage = (
            CarWash.objects.select_related("site")
            .annotate(photo_count_value=Count("photos", distinct=True))
            .prefetch_related(PHOTO_PREFETCH)
            .get(pk=lavage.pk)
        )
        return Response(
            {
                "message": "Lavage enregistré avec succès.",
                "lavage": EmployeeCarWashDetailSerializer(lavage, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class EmployeeCarWashDetailApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request, lavage_id):
        lavage = get_object_or_404(
            CarWash.objects.select_related("site", "employe")
            .annotate(photo_count_value=Count("photos", distinct=True))
            .prefetch_related(PHOTO_PREFETCH),
            id=lavage_id,
            employe=request.user,
        )
        return Response(EmployeeCarWashDetailSerializer(lavage, context={"request": request}).data)


class EmployeeIssueListCreateApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        queryset = (
            request.user.problemes_signales.select_related("site", "traite_par")
            .order_by("-created_at")
        )
        return _paginate(self, queryset, EmployeeIssueSerializer, request, page_size=12)

    def post(self, request):
        profile = _employee_profile(request.user)
        categorie = str(request.data.get("categorie", "")).strip()
        description = str(request.data.get("description", "")).strip()
        photo = request.FILES.get("photo")

        if categorie not in {choice[0] for choice in IssueReport.CATEGORIE_CHOICES}:
            return Response({"message": "Catégorie invalide."}, status=status.HTTP_400_BAD_REQUEST)
        if not description:
            return Response({"message": "La description est requise."}, status=status.HTTP_400_BAD_REQUEST)

        probleme = IssueReport.objects.create(
            employe=request.user,
            site=profile.site,
            categorie=categorie,
            description=description,
            photo=photo,
            statut="OUVERT",
        )
        _send_issue_report_notification(probleme)

        AuditLog.log(
            user=request.user,
            action="CREER",
            description=f"Nouveau problème signalé: {probleme.get_categorie_display()}",
            content_object=probleme,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        return Response(
            {
                "message": "Problème signalé avec succès.",
                "probleme": EmployeeIssueSerializer(probleme, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class EmployeeIssueDetailApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request, probleme_id):
        probleme = get_object_or_404(
            IssueReport.objects.select_related("site", "employe", "traite_par"),
            id=probleme_id,
            employe=request.user,
        )
        return Response(EmployeeIssueSerializer(probleme, context={"request": request}).data)


class EmployeeDailyReportApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        user = request.user
        today = timezone.localdate()
        profile = _employee_profile(user)
        shift, _created = ShiftDay.objects.get_or_create(
            employe=user,
            date=today,
            defaults={"site": profile.site},
        )
        today_washes = (
            CarWash.objects.filter(employe=user, site=profile.site, date=today)
            .annotate(photo_count_value=Count("photos", distinct=True))
            .prefetch_related(PHOTO_PREFETCH)
            .order_by("-created_at")
        )
        today_issues = IssueReport.objects.filter(
            employe=user,
            site=profile.site,
            created_at__date=today,
        ).order_by("-created_at")

        return Response(
            {
                "today": today.isoformat(),
                "site": SiteSummarySerializer(profile.site).data,
                "shift": _safe_employee_shift(shift),
                "report_submitted": shift.daily_report_confirmed,
                "submitted_total_amount": (
                    f"{Decimal(shift.total_amount_reported_fc or 0):.2f}"
                    if shift.daily_report_confirmed else ""
                ),
                "expense_form": _build_initial_daily_expense_form(shift),
                "computed_total_washes": today_washes.count(),
                "today_washes": EmployeeCarWashSerializer(today_washes, many=True, context={"request": request}).data,
                "today_issues": EmployeeIssueSerializer(today_issues, many=True, context={"request": request}).data,
            }
        )

    def post(self, request):
        user = request.user
        today = timezone.localdate()
        profile = _employee_profile(user)
        shift, _created = ShiftDay.objects.get_or_create(
            employe=user,
            date=today,
            defaults={"site": profile.site},
        )
        total_amount_value = str(request.data.get("total_amount_reported_fc", "")).strip()
        expense_form = _parse_daily_expenses_form(request.data)

        try:
            total_amount_reported = Decimal(total_amount_value or "0")
            if total_amount_reported < 0:
                raise ValueError
        except (ArithmeticError, ValueError):
            return Response(
                {"message": "Veuillez entrer une valeur valide pour le montant total."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if expense_form["errors"]:
            return Response({"message": expense_form["errors"][0], "errors": expense_form["errors"]}, status=status.HTTP_400_BAD_REQUEST)

        today_washes = CarWash.objects.filter(employe=user, site=profile.site, date=today).order_by("-created_at")
        today_issues = IssueReport.objects.filter(employe=user, site=profile.site, created_at__date=today)
        was_update = shift.daily_report_confirmed
        shift.site = profile.site
        shift.total_amount_reported_fc = total_amount_reported
        shift.total_lavages_reported = today_washes.count()
        shift.lavages_review = ""
        shift.problems_review = ""
        shift.report_notes = ""
        shift.daily_expenses = expense_form["items"]
        shift.daily_expenses_total_fc = expense_form["total"]
        shift.daily_report_confirmed = True
        shift.save()
        sync_site_finance_from_daily_reports(profile.site, today, actor=user)
        computed_total_amount = today_washes.aggregate(total=Sum("montant"))["total"] or Decimal("0")
        _send_final_report_notification(
            shift=shift,
            computed_total_amount=computed_total_amount,
            issue_count=today_issues.count(),
            was_update=was_update,
        )
        AuditLog.log(
            user=user,
            action="AUTRE",
            description=f"Rapport journalier employé {'mis à jour' if was_update else 'enregistré'}: {profile.site.nom} - {today}",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        return Response(
            {
                "message": "Rapport de la journée mis à jour avec succès." if was_update else "Rapport de la journée enregistré avec succès.",
                "shift": _safe_employee_shift(shift),
            }
        )


class EmployeeWaterPurchaseApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        profile = _employee_profile(request.user)
        today = timezone.localdate()
        billing_month = today.replace(day=1)
        today_purchase = (
            SiteWaterPurchase.objects.filter(site=profile.site, purchase_date=today)
            .select_related("created_by", "supplier")
            .order_by("-created_at")
            .first()
        )
        month_purchases_qs = (
            SiteWaterPurchase.objects.filter(site=profile.site, billing_month=billing_month)
            .select_related("created_by", "supplier")
            .order_by("-purchase_date", "-created_at")
        )
        last_purchase = month_purchases_qs.first()
        default_supplier = get_default_water_supplier()

        return Response(
            {
                "today": today.isoformat(),
                "site": SiteSummarySerializer(profile.site).data,
                "billing_month": billing_month.isoformat(),
                "billing_month_display": billing_month.strftime("%m/%Y"),
                "default_supplier_name": default_supplier.name,
                "today_purchase": EmployeeWaterPurchaseSerializer(today_purchase).data if today_purchase else None,
                "month_purchase_count": month_purchases_qs.count(),
                "last_purchase": EmployeeWaterPurchaseSerializer(last_purchase).data if last_purchase else None,
            }
        )

    def post(self, request):
        profile = _employee_profile(request.user)
        today = timezone.localdate()
        billing_month = today.replace(day=1)
        if SiteWaterPurchase.objects.filter(site=profile.site, purchase_date=today).exists():
            return Response(
                {
                    "message": "L'achat d'eau du jour a déjà été signalé. L'administrateur peut le corriger si nécessaire.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        default_supplier = get_default_water_supplier()
        default_amount = get_water_purchase_default_amount(billing_month, supplier=default_supplier)
        reporter_name = request.user.get_full_name() or request.user.username
        purchase = SiteWaterPurchase.objects.create(
            site=profile.site,
            supplier=default_supplier,
            billing_month=billing_month,
            purchase_date=today,
            amount_fc=default_amount,
            notes=f"Signalé via portail employé par {reporter_name}.",
            created_by=request.user,
        )
        _send_water_purchase_notification(purchase)
        AuditLog.log(
            user=request.user,
            action="AUTRE",
            description=(
                f"Achat d'eau signalé via portail employé: "
                f"{profile.site.nom} - {default_supplier.name} - {purchase.purchase_date}"
            ),
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return Response(
            {
                "message": "Achat d'eau enregistré pour aujourd'hui.",
                "purchase": EmployeeWaterPurchaseSerializer(purchase).data,
            },
            status=status.HTTP_201_CREATED,
        )


class EmployeeFuelPurchaseApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        profile = _employee_profile(request.user)
        today = timezone.localdate()
        billing_month = today.replace(day=1)
        today_purchase = (
            SiteFuelPurchase.objects.filter(site=profile.site, purchase_date=today)
            .select_related("created_by")
            .order_by("-created_at")
            .first()
        )
        month_purchases_qs = (
            SiteFuelPurchase.objects.filter(site=profile.site, billing_month=billing_month)
            .select_related("created_by")
            .order_by("-purchase_date", "-created_at")
        )
        last_purchase = month_purchases_qs.first()

        return Response(
            {
                "today": today.isoformat(),
                "site": SiteSummarySerializer(profile.site).data,
                "billing_month": billing_month.isoformat(),
                "billing_month_display": billing_month.strftime("%m/%Y"),
                "today_purchase": EmployeeFuelPurchaseSerializer(today_purchase).data if today_purchase else None,
                "month_purchase_count": month_purchases_qs.count(),
                "last_purchase": EmployeeFuelPurchaseSerializer(last_purchase).data if last_purchase else None,
            }
        )

    def post(self, request):
        profile = _employee_profile(request.user)
        today = timezone.localdate()
        billing_month = today.replace(day=1)
        if SiteFuelPurchase.objects.filter(site=profile.site, purchase_date=today).exists():
            return Response(
                {
                    "message": "L'achat de carburant du jour a déjà été signalé. L'administrateur peut le corriger si nécessaire.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        reporter_name = request.user.get_full_name() or request.user.username
        purchase = SiteFuelPurchase.objects.create(
            site=profile.site,
            billing_month=billing_month,
            purchase_date=today,
            notes=f"Signalé via portail employé par {reporter_name}.",
            created_by=request.user,
        )
        _send_fuel_purchase_notification(purchase)
        AuditLog.log(
            user=request.user,
            action="AUTRE",
            description=(
                f"Achat de carburant signalé via portail employé: "
                f"{profile.site.nom} - {purchase.purchase_date}"
            ),
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return Response(
            {
                "message": "Achat de carburant enregistré pour aujourd'hui.",
                "purchase": EmployeeFuelPurchaseSerializer(purchase).data,
            },
            status=status.HTTP_201_CREATED,
        )


class EmployeeHistorySummaryApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        profile = _employee_profile(request.user)
        today = timezone.localdate()
        return Response(
            {
                "site": SiteSummarySerializer(profile.site).data,
                "counts": {
                    "pointages": ShiftDay.objects.filter(employe=request.user).count(),
                    "rapports": ShiftDay.objects.filter(employe=request.user, daily_report_confirmed=True).count(),
                    "rapports_en_attente": ShiftDay.objects.filter(
                        employe=request.user,
                        clock_in_time__isnull=False,
                        daily_report_confirmed=False,
                    ).count(),
                    "lavages": request.user.lavages.count(),
                    "problemes": request.user.problemes_signales.count(),
                    "eau_mois": SiteWaterPurchase.objects.filter(
                        site=profile.site,
                        billing_month=today.replace(day=1),
                    ).count(),
                    "carburant_mois": SiteFuelPurchase.objects.filter(
                        site=profile.site,
                        billing_month=today.replace(day=1),
                    ).count(),
                },
            }
        )


class EmployeeHistoryPointagesApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        queryset = (
            ShiftDay.objects.filter(employe=request.user)
            .select_related("site")
            .order_by("-date", "-clock_in_time")
        )
        return _paginate(self, queryset, EmployeeShiftHistorySerializer, request, page_size=10)


class EmployeeHistoryReportsApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        queryset = (
            ShiftDay.objects.filter(employe=request.user)
            .select_related("site")
            .order_by("-date", "-updated_at")
        )
        return _paginate(self, queryset, EmployeeShiftHistorySerializer, request, page_size=10)


class EmployeeHistoryWaterApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        profile = _employee_profile(request.user)
        queryset = (
            SiteWaterPurchase.objects.filter(site=profile.site)
            .select_related("created_by", "supplier")
            .order_by("-purchase_date", "-created_at")
        )
        return _paginate(self, queryset, EmployeeWaterPurchaseSerializer, request, page_size=10)


class EmployeeHistoryFuelApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        profile = _employee_profile(request.user)
        queryset = (
            SiteFuelPurchase.objects.filter(site=profile.site)
            .select_related("created_by")
            .order_by("-purchase_date", "-created_at")
        )
        return _paginate(self, queryset, EmployeeFuelPurchaseSerializer, request, page_size=10)


class ManagerDashboardApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        today = timezone.localdate()
        start_date, end_date, date_debut, date_fin, selected_period_label = _parse_dashboard_date_range(request, today)
        sites = list(_manager_accessible_sites(request.user))
        site_ids = [site.id for site in sites]

        employee_counts = {
            item["site"]: item["total"]
            for item in UserProfile.objects.filter(
                site_id__in=site_ids,
                role=UserProfile.EMPLOYEE_ROLE,
                actif=True,
            ).values("site").annotate(total=Count("id"))
        }
        pointage_stats = {
            item["site"]: item
            for item in ShiftDay.objects.filter(
                site_id__in=site_ids,
                date__gte=start_date,
                date__lte=end_date,
            ).values("site").annotate(
                presents=Count("id", filter=Q(clock_in_time__isnull=False)),
                missed_punch=Count("id", filter=Q(clock_in_time__isnull=False, clock_out_time__isnull=True)),
            )
        }
        wash_stats = {
            item["site"]: item
            for item in CarWash.objects.filter(
                site_id__in=site_ids,
                date__gte=start_date,
                date__lte=end_date,
            ).values("site").annotate(total_lavages=Count("id"), chiffre_jour=Sum("montant"))
        }
        issue_stats = {
            item["site"]: item["problemes_ouverts"]
            for item in IssueReport.objects.filter(
                site_id__in=site_ids,
                statut__in=["OUVERT", "EN_COURS"],
            ).values("site").annotate(problemes_ouverts=Count("id"))
        }

        cards = []
        for site in sites:
            total_employes = employee_counts.get(site.id, 0)
            pointage_summary = pointage_stats.get(site.id, {})
            wash_summary = wash_stats.get(site.id, {})
            presents = pointage_summary.get("presents", 0)
            cards.append(
                {
                    "site_id": str(site.id),
                    "site_name": site.nom,
                    "total_employes": total_employes,
                    "presents": presents,
                    "absents": max(total_employes - presents, 0),
                    "missed_punch": pointage_summary.get("missed_punch", 0),
                    "total_lavages": wash_summary.get("total_lavages", 0),
                    "revenue_fc": str(wash_summary.get("chiffre_jour") or 0),
                    "revenue_display": _fc_display(wash_summary.get("chiffre_jour") or 0),
                    "problemes_ouverts": issue_stats.get(site.id, 0),
                }
            )

        return Response(
            {
                "today": today.isoformat(),
                "date_debut": date_debut,
                "date_fin": date_fin,
                "selected_period_label": selected_period_label,
                "sites": cards,
                "available_sites": _site_options(sites),
            }
        )


class ManagerPointageListApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        accessible_sites = list(_manager_accessible_sites(request.user))
        site_ids = [site.id for site in accessible_sites]
        queryset = ShiftDay.objects.select_related("employe", "site", "corrected_by").filter(site_id__in=site_ids).order_by("-date", "-clock_in_time")

        date_debut = request.query_params.get("date_debut")
        date_fin = request.query_params.get("date_fin")
        employe_id = request.query_params.get("employe")
        site_id = request.query_params.get("site")
        if date_debut:
            queryset = queryset.filter(date__gte=date_debut)
        if date_fin:
            queryset = queryset.filter(date__lte=date_fin)
        if employe_id:
            queryset = queryset.filter(employe_id=employe_id)
        if site_id:
            queryset = queryset.filter(site_id=site_id)

        return _paginate(
            self,
            queryset,
            ShiftDaySerializer,
            request,
            page_size=20,
            extra={
                "filters": {
                    "sites": _site_options(accessible_sites),
                    "employees": _employee_options_for_sites(site_ids),
                }
            },
        )


class ManagerPointageCorrectionApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, pointage_id):
        accessible_site_ids = {site.id for site in _manager_accessible_sites(request.user)}
        pointage = get_object_or_404(ShiftDay.objects.select_related("site", "employe"), id=pointage_id, site_id__in=accessible_site_ids)
        motif = str(request.data.get("motif", "")).strip()
        if not motif:
            return Response({"message": "Le motif de correction est obligatoire."}, status=status.HTTP_400_BAD_REQUEST)

        new_clock_in = str(request.data.get("clock_in_time", "")).strip()
        new_clock_out = str(request.data.get("clock_out_time", "")).strip()
        before = {
            "clock_in_time": str(pointage.clock_in_time),
            "clock_out_time": str(pointage.clock_out_time) if pointage.clock_out_time else None,
        }

        try:
            if new_clock_in:
                clock_in_dt = datetime.strptime(f"{pointage.date} {new_clock_in}", "%Y-%m-%d %H:%M")
                pointage.clock_in_time = timezone.make_aware(clock_in_dt)
            if new_clock_out:
                clock_out_dt = datetime.strptime(f"{pointage.date} {new_clock_out}", "%Y-%m-%d %H:%M")
                pointage.clock_out_time = timezone.make_aware(clock_out_dt)
        except ValueError:
            return Response({"message": "Format d'heure invalide."}, status=status.HTTP_400_BAD_REQUEST)

        pointage.corrected_by = request.user
        pointage.correction_reason = motif
        pointage.corrected_at = timezone.now()
        pointage.save()

        AuditLog.log(
            user=request.user,
            action="CORRIGER_POINTAGE",
            description=f"Pointage corrigé: {pointage}",
            motif=motif,
            content_object=pointage,
            donnees_avant=before,
            donnees_apres={
                "clock_in_time": str(pointage.clock_in_time),
                "clock_out_time": str(pointage.clock_out_time) if pointage.clock_out_time else None,
            },
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return Response(
            {
                "message": "Pointage corrigé avec succès.",
                "pointage": ShiftDaySerializer(pointage).data,
            }
        )


class ManagerPointageDetailApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request, pointage_id):
        accessible_site_ids = {site.id for site in _manager_accessible_sites(request.user)}
        pointage = get_object_or_404(
            ShiftDay.objects.select_related("site", "employe", "corrected_by"),
            id=pointage_id,
            site_id__in=accessible_site_ids,
        )
        return Response(ShiftDaySerializer(pointage).data)


class ManagerCarWashListApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        accessible_sites = list(_manager_accessible_sites(request.user))
        site_ids = [site.id for site in accessible_sites]
        queryset = (
            CarWash.objects.select_related("employe", "site")
            .annotate(photo_count_value=Count("photos", distinct=True))
            .prefetch_related(PHOTO_PREFETCH)
            .filter(site_id__in=site_ids)
            .order_by("-created_at")
        )

        date_debut = request.query_params.get("date_debut")
        date_fin = request.query_params.get("date_fin")
        employe_id = request.query_params.get("employe")
        type_service = request.query_params.get("type_service")
        site_id = request.query_params.get("site")
        if date_debut:
            queryset = queryset.filter(date__gte=date_debut)
        if date_fin:
            queryset = queryset.filter(date__lte=date_fin)
        if employe_id:
            queryset = queryset.filter(employe_id=employe_id)
        if type_service:
            queryset = queryset.filter(type_service=type_service)
        if site_id:
            queryset = queryset.filter(site_id=site_id)

        total_montant = queryset.aggregate(total=Sum("montant"))["total"] or Decimal("0")
        total_count = queryset.count()

        return _paginate(
            self,
            queryset,
            ManagerCarWashSerializer,
            request,
            page_size=20,
            extra={
                "totals": {
                    "count": total_count,
                    "amount_fc": str(total_montant),
                    "amount_display": _fc_display(total_montant),
                },
                "filters": {
                    "sites": _site_options(accessible_sites),
                    "employees": _employee_options_for_sites(site_ids),
                    "types_service": [
                        {"value": value, "label": label}
                        for value, label in CarWash.TYPE_SERVICE_CHOICES
                    ],
                },
            },
        )


class ManagerIssueListApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        accessible_sites = list(_manager_accessible_sites(request.user))
        site_ids = [site.id for site in accessible_sites]
        queryset = (
            IssueReport.objects.select_related("employe", "site", "traite_par")
            .filter(site_id__in=site_ids)
            .order_by("-created_at")
        )

        statut = request.query_params.get("statut")
        categorie = request.query_params.get("categorie")
        site_id = request.query_params.get("site")
        if statut:
            queryset = queryset.filter(statut=statut)
        if categorie:
            queryset = queryset.filter(categorie=categorie)
        if site_id:
            queryset = queryset.filter(site_id=site_id)

        return _paginate(
            self,
            queryset,
            ManagerIssueSerializer,
            request,
            page_size=20,
            extra={
                "filters": {
                    "sites": _site_options(accessible_sites),
                    "statuts": [
                        {"value": value, "label": label}
                        for value, label in IssueReport.STATUT_CHOICES
                    ],
                    "categories": [
                        {"value": value, "label": label}
                        for value, label in IssueReport.CATEGORIE_CHOICES
                    ],
                }
            },
        )


class ManagerQrDetailApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request, site_id):
        site = get_object_or_404(_manager_accessible_sites(request.user), id=site_id)
        qr_url = request.build_absolute_uri(site.get_qr_url())
        return Response(
            {
                "site": SiteSummarySerializer(site).data,
                "qr_image": generate_qr_code_image(qr_url),
                "qr_url": qr_url,
                "site_token": str(site.site_token),
                "gps": {
                    "actif": site.gps_actif,
                    "latitude": str(site.latitude or ""),
                    "longitude": str(site.longitude or ""),
                    "rayon_autorisé_mètres": site.rayon_autorisé_mètres,
                },
            }
        )


class ManagerQrRegenerateApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, site_id):
        site = get_object_or_404(_manager_accessible_sites(request.user), id=site_id)
        motif = str(request.data.get("motif", "")).strip()
        if not motif:
            return Response({"message": "Le motif de régénération est obligatoire."}, status=status.HTTP_400_BAD_REQUEST)

        old_token = str(site.site_token)
        import uuid

        site.site_token = uuid.uuid4()
        site.save()
        AuditLog.log(
            user=request.user,
            action="REGENERER_QR",
            description=f"QR fixe régénéré pour {site.nom}",
            motif=motif,
            content_object=site,
            donnees_avant={"site_token": old_token},
            donnees_apres={"site_token": str(site.site_token)},
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return Response({"message": "QR code régénéré avec succès."})
