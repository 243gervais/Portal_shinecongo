from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User
from django.core.cache import cache
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
from comptes.image_utils import extract_image_capture_datetime
from comptes.models import UserProfile
from lavages.models import CarWash, CarWashPhoto
from pointage.attendance import (
    attendance_schedule_context,
    get_clock_in_status,
    get_clock_out_status,
    is_workday,
)
from pointage.models import ManagerEquipmentPhoto, ShiftDay
from pointage.report_sync import sync_site_finance_from_daily_reports
from pointage.utils import generate_qr_code_image, get_client_ip, get_user_agent
from pointage.views import (
    _build_initial_daily_expense_form,
    _parse_required_fuel_purchase_amount,
    _parse_daily_expenses_form,
    _send_fuel_purchase_notification,
    _send_final_report_notification,
    _send_water_purchase_notification,
)
from pointage.views_manager import _parse_dashboard_date_range
from problemes.models import IssueReport
from problemes.views import _send_issue_report_notification
from sites.models import (
    Location,
    ManagerManualMachine,
    ManagerManualSettings,
    ManagerManualSupplier,
    SiteFuelPurchase,
    SiteWaterPurchase,
    WaterSupplier,
    get_default_water_supplier,
)

from .pagination import PortalPagination
from .permissions import IsManagerOrAdmin, IsPortalEmployee, IsPortalSelfAttendanceUser
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
PHOTO_COUNT_PREFETCH = Prefetch(
    "photos",
    queryset=CarWashPhoto.objects.only("id", "lavage_id").order_by(),
    to_attr="prefetched_photo_count_items",
)

MANAGER_DASHBOARD_CACHE_SECONDS = 45
PORTAL_SUMMARY_CACHE_SECONDS = 30
REPORT_PREVIEW_LIMIT = 30
LAVAGE_LIST_SERIALIZER_CONTEXT = {"include_image_previews": False}
MANAGER_WATER_STANDARD_SUPPLIERS = [
    {"key": "honosha", "label": "Honosha", "lookup": "honosha"},
    {"key": "muswahili", "label": "Muswahili", "lookup": "muswahili"},
]

DEFAULT_MANUAL_SECTIONS = [
    {
        "id": "vue-ensemble",
        "title": "Vue d'ensemble",
        "items": [
            "Le manager protège la qualité du service, la discipline de l'équipe et la réputation de Shine Congo.",
            "Le portail manager sert à suivre les lavages, les présences, les incidents, l'eau, le carburant et le rapport quotidien.",
            "Le manager ne voit pas les montants financiers sensibles dans son portail; il suit surtout le volume de véhicules et la qualité opérationnelle.",
        ],
    },
    {
        "id": "responsabilites",
        "title": "Responsabilités du manager",
        "items": [
            "Ouvrir le site à l'heure, contrôler la propreté de l'espace et vérifier que chaque employé pointe sa présence.",
            "Suivre chaque lavage avec photos, plaque quand disponible, type de véhicule et remarques utiles.",
            "Signaler immédiatement les problèmes de machine, d'eau, de carburant, de client ou de discipline.",
            "Envoyer le rapport quotidien complet avant la fermeture.",
        ],
    },
    {
        "id": "journee-reussie",
        "title": "Exemple d'une journée réussie",
        "items": [
            "Tous les employés pointent le début et la fin de journée avec photo.",
            "Les véhicules sont enregistrés au fur et à mesure, sans attendre la fin de journée.",
            "Le site reste propre, les machines sont rangées, les produits sont contrôlés et les clients sont accueillis rapidement.",
            "Le manager envoie le rapport final avec les observations, achats d'eau, carburant et incidents éventuels.",
        ],
    },
    {
        "id": "consommables",
        "title": "Consommables",
        "items": [
            "Contrôler chaque matin le savon, les chiffons, les brosses, les seaux, le carburant et l'eau.",
            "Signaler tout achat d'eau ou de carburant dans le portail le jour même.",
            "Éviter le gaspillage: un bon lavage utilise le strict nécessaire sans réduire la qualité.",
        ],
    },
    {
        "id": "checklist",
        "title": "Checklist quotidienne",
        "items": [
            "Présence personnelle du manager enregistrée.",
            "Présence des employés contrôlée.",
            "Machines testées avant les premiers clients.",
            "Stock d'eau, carburant et consommables vérifié.",
            "Lavages enregistrés avec photos.",
            "Incidents signalés immédiatement.",
            "Rapport quotidien envoyé en fin de journée.",
        ],
    },
    {
        "id": "incidents",
        "title": "Gestion des incidents",
        "items": [
            "Sécuriser d'abord les personnes, les clients, les véhicules et les machines.",
            "Créer un signalement dans le portail avec une description claire et des photos si possible.",
            "Prévenir l'admin si l'incident bloque le travail, touche un client ou nécessite une dépense.",
        ],
    },
    {
        "id": "employes",
        "title": "Gestion des employés",
        "items": [
            "Contrôler les retards, absences, sorties manquantes et comportements non professionnels.",
            "Corriger un pointage uniquement avec un motif clair et honnête.",
            "Aider l'équipe à travailler vite, proprement et avec respect.",
        ],
    },
    {
        "id": "service-client",
        "title": "Service client",
        "items": [
            "Accueillir rapidement chaque client, expliquer le service et garder un ton calme.",
            "Vérifier la satisfaction avant le départ du véhicule.",
            "Transformer les plaintes en signalements clairs, avec action immédiate quand c'est possible.",
        ],
    },
    {
        "id": "rapports",
        "title": "Rapports quotidiens",
        "items": [
            "Le rapport final doit résumer les lavages, présences, incidents, eau, carburant et remarques de la journée.",
            "Ne pas attendre plusieurs jours pour signaler une information opérationnelle.",
            "Un bon rapport permet à l'admin de comprendre la journée sans appeler plusieurs personnes.",
        ],
    },
    {
        "id": "vision",
        "title": "Vision de Shine Congo",
        "items": [
            "Shine Congo doit être un service fiable, propre, rapide et respectueux.",
            "Le manager est le gardien du standard sur le terrain.",
            "Chaque lavage bien fait, chaque rapport clair et chaque client respecté construit la marque.",
        ],
    },
]

DEFAULT_MACHINE_CARDS = [
    {
        "name": "Nettoyeur haute pression",
        "purpose": "Laver rapidement l'extérieur des véhicules et enlever la saleté avant finition.",
        "maintenance": "Vérifier le carburant ou l'alimentation, nettoyer le filtre, éviter de tirer le tuyau brutalement et ranger la lance après usage.",
        "troubleshooting": "Si la pression baisse, vérifier l'eau, le filtre, les raccords et le carburant avant de déclarer une panne.",
    },
    {
        "name": "Aspirateur",
        "purpose": "Nettoyer l'intérieur des voitures, tapis, sièges et zones difficiles.",
        "maintenance": "Vider le bac régulièrement, nettoyer le filtre et garder le câble loin de l'eau.",
        "troubleshooting": "Si l'aspiration diminue, vider le bac, contrôler le filtre et vérifier que le tuyau n'est pas bouché.",
    },
]

DEFAULT_SUPPLIER_CARDS = [
    {
        "name": "Honosha's Forage",
        "category": "EAU",
        "contact_name": "",
        "phone": "",
        "service_notes": "Fournisseur d'eau par défaut. Confirmer le remplissage et signaler l'achat dans le portail.",
    },
    {
        "name": "Station carburant locale",
        "category": "CARBURANT",
        "contact_name": "",
        "phone": "",
        "service_notes": "Utiliser pour le carburant des machines. Signaler chaque achat le jour même.",
    },
]


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


def _self_attendance_profile(user):
    profile = _profile(user)
    if not profile or not (profile.is_employe() or profile.is_manager()) or not profile.site_id:
        return None
    return profile


def _can_view_manager_money(user):
    if user.is_superuser:
        return True
    profile = _profile(user)
    return bool(profile and profile.is_admin())


def _is_location_manager(user):
    profile = _profile(user)
    return bool(profile and profile.is_manager() and not user.is_superuser)


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


def _manager_selected_site(user, request):
    accessible_sites = list(_manager_accessible_sites(user))
    requested_site_id = request.data.get("site") or request.query_params.get("site")
    if requested_site_id:
        for site in accessible_sites:
            if str(site.id) == str(requested_site_id):
                return site, accessible_sites
        return None, accessible_sites
    if len(accessible_sites) == 1:
        return accessible_sites[0], accessible_sites
    profile = _profile(user)
    if profile and profile.site_id:
        for site in accessible_sites:
            if site.id == profile.site_id:
                return site, accessible_sites
    return (accessible_sites[0] if accessible_sites else None), accessible_sites


def _manager_visible_staff_roles(user):
    roles = [UserProfile.EMPLOYEE_ROLE]
    if _can_view_manager_money(user):
        roles.append(UserProfile.MANAGER_ROLE)
    return roles


def _employee_options_for_sites(site_ids, user=None):
    roles = _manager_visible_staff_roles(user) if user else [UserProfile.EMPLOYEE_ROLE]
    cache_key = (
        "portal:employee-options:"
        + ",".join(sorted(str(site_id) for site_id in site_ids))
        + ":roles:"
        + ",".join(sorted(roles))
    )
    cached_options = cache.get(cache_key)
    if cached_options is not None:
        return cached_options

    queryset = (
        User.objects.filter(
            userprofile__site_id__in=site_ids,
            userprofile__role__in=roles,
            userprofile__actif=True,
        )
        .order_by("first_name", "last_name", "username")
        .distinct()
    )
    options = [
        {
            "id": employee.id,
            "nom": employee.get_full_name() or employee.username,
        }
        for employee in queryset
    ]
    cache.set(cache_key, options, 60)
    return options


def _parse_portal_date(value):
    if not value:
        return timezone.localdate()
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Format de date invalide.") from exc


def _parse_portal_time(target_date, value):
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError("L'heure est obligatoire.")
    try:
        parsed_time = datetime.strptime(cleaned, "%H:%M").time()
    except ValueError as exc:
        raise ValueError("Format d'heure invalide.") from exc
    return timezone.make_aware(datetime.combine(target_date, parsed_time))


def _manager_team_attendance_rows(site, target_date, request):
    employees = list(
        User.objects.filter(
            userprofile__site=site,
            userprofile__role=UserProfile.EMPLOYEE_ROLE,
            userprofile__actif=True,
        )
        .select_related("userprofile")
        .order_by("first_name", "last_name", "username")
    )
    shifts_by_employee_id = {
        shift.employe_id: shift
        for shift in ShiftDay.objects.filter(site=site, date=target_date, employe__in=employees)
        .select_related("employe", "site", "corrected_by")
    }
    rows = []
    for employee in employees:
        shift = shifts_by_employee_id.get(employee.id)
        rows.append(
            {
                "employee_id": employee.id,
                "employee_name": employee.get_full_name() or employee.username,
                "shift": ShiftDaySerializer(shift, context={"request": request}).data if shift else None,
                "attendance_status": (
                    shift.get_clock_in_attendance_status()
                    if shift else get_clock_in_status(target_date, None)
                ),
                "clock_out_status": (
                    shift.get_clock_out_attendance_status()
                    if shift else get_clock_out_status(target_date, None)
                ),
            }
        )
    return rows


def _file_url(request, file_field):
    if not file_field:
        return ""
    try:
        return request.build_absolute_uri(file_field.url)
    except ValueError:
        return ""


def _first_manual_settings():
    return ManagerManualSettings.objects.order_by("id").first() or ManagerManualSettings()


def _machine_payload(machine, request):
    return {
        "id": machine.pk,
        "name": machine.name,
        "purpose": machine.purpose,
        "maintenance": machine.maintenance,
        "troubleshooting": machine.troubleshooting,
        "image_url": _file_url(request, machine.image),
        "training_video_url": _file_url(request, machine.training_video),
    }


def _equipment_photo_payload(photo, request):
    return {
        "id": photo.pk,
        "machine_id": photo.machine_id,
        "machine_name": photo.machine_name,
        "photo_url": _file_url(request, photo.photo),
        "uploaded_at": timezone.localtime(photo.uploaded_at).strftime("%d/%m/%Y %H:%M"),
    }


def _manager_equipment_checklist(machines, report, request):
    photos_by_machine = {}
    if report:
        for photo in (
            ManagerEquipmentPhoto.objects.filter(daily_report=report)
            .select_related("machine")
            .order_by("machine__display_order", "machine_name", "uploaded_at")
        ):
            photos_by_machine.setdefault(photo.machine_id, []).append(_equipment_photo_payload(photo, request))

    return [
        {
            **_machine_payload(machine, request),
            "submitted_photos": photos_by_machine.get(machine.pk, []),
            "submitted_photo_count": len(photos_by_machine.get(machine.pk, [])),
        }
        for machine in machines
    ]


def _default_machine_payload(item):
    return {
        "id": None,
        "name": item["name"],
        "purpose": item["purpose"],
        "maintenance": item["maintenance"],
        "troubleshooting": item["troubleshooting"],
        "image_url": "",
        "training_video_url": "",
    }


def _supplier_payload(supplier, request):
    return {
        "id": supplier.pk,
        "name": supplier.name,
        "category": supplier.get_category_display(),
        "contact_name": supplier.contact_name,
        "phone": supplier.phone,
        "service_notes": supplier.service_notes,
        "image_url": _file_url(request, supplier.image),
    }


def _default_supplier_payload(item):
    return {
        "id": None,
        "name": item["name"],
        "category": item["category"].title(),
        "contact_name": item["contact_name"],
        "phone": item["phone"],
        "service_notes": item["service_notes"],
        "image_url": "",
    }


def _water_supplier_for_standard_choice(choice):
    supplier_config = next(
        (item for item in MANAGER_WATER_STANDARD_SUPPLIERS if item["key"] == choice),
        None,
    )
    if not supplier_config:
        return None

    supplier = (
        WaterSupplier.objects.filter(name__icontains=supplier_config["lookup"])
        .order_by("-is_active", "-is_default", "name")
        .first()
    )
    if supplier:
        if not supplier.is_active:
            supplier.is_active = True
            supplier.save(update_fields=["is_active", "updated_at"])
        return supplier

    default_price = get_default_water_supplier().price_per_tank_fc
    return WaterSupplier.objects.create(
        name=supplier_config["label"],
        price_per_tank_fc=default_price,
        is_active=True,
        is_default=False,
        notes="Créé automatiquement depuis le portail manager.",
    )


def _manager_water_supplier_options():
    options = []
    for supplier_config in MANAGER_WATER_STANDARD_SUPPLIERS:
        options.append(
            {
                "value": supplier_config["key"],
                "label": supplier_config["label"],
                "requires_custom": False,
            }
        )
    options.append(
        {
            "value": "other",
            "label": "Autre",
            "requires_custom": True,
        }
    )
    return options


def _parse_manager_water_supplier(data, billing_month):
    selected = str(data.get("supplier_choice", "")).strip().lower()
    if selected in {"", "default"}:
        selected = "honosha"

    if selected == "other":
        supplier_name = str(data.get("other_supplier_name", "")).strip()
        amount_raw = str(data.get("amount_fc", "")).strip()
        if not supplier_name:
            raise ValueError("Veuillez saisir le nom du fournisseur d'eau.")
        if len(supplier_name) > 200:
            raise ValueError("Le nom du fournisseur est trop long.")
        try:
            amount_fc = Decimal(amount_raw)
            if amount_fc <= 0:
                raise InvalidOperation
        except (ArithmeticError, InvalidOperation, TypeError, ValueError):
            raise ValueError("Veuillez saisir le prix de l'eau acheté.")
        supplier, _created = WaterSupplier.objects.get_or_create(
            name=supplier_name,
            defaults={
                "price_per_tank_fc": amount_fc,
                "is_active": True,
                "is_default": False,
                "notes": "Fournisseur ajouté depuis le portail manager.",
            },
        )
        if not supplier.is_active or supplier.price_per_tank_fc != amount_fc:
            supplier.is_active = True
            supplier.price_per_tank_fc = amount_fc
            supplier.save(update_fields=["is_active", "price_per_tank_fc", "updated_at"])
        return supplier, amount_fc

    supplier = _water_supplier_for_standard_choice(selected)
    if not supplier:
        raise ValueError("Veuillez choisir Honosha, Muswahili ou Autre.")
    return supplier, get_water_purchase_default_amount(billing_month, supplier=supplier)


def _paginate(view, queryset, serializer_class, request, *, page_size=12, extra=None, serializer_context=None):
    paginator = PortalPagination()
    paginator.page_size = page_size
    page = paginator.paginate_queryset(queryset, request, view=view)
    context = {"request": request}
    if serializer_context:
        context.update(serializer_context)
    serializer = serializer_class(page, many=True, context=context)
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


def _manager_report_attendance_rows(site, report_date):
    pointages = (
        ShiftDay.objects.filter(
            site=site,
            date=report_date,
            clock_in_time__isnull=False,
            employe__userprofile__role__in=[UserProfile.EMPLOYEE_ROLE, UserProfile.MANAGER_ROLE],
        )
        .select_related("employe", "employe__userprofile", "site")
        .order_by("clock_in_time", "employe__first_name", "employe__last_name", "employe__username")
    )
    rows = []
    for pointage in pointages:
        profile = getattr(pointage.employe, "userprofile", None)
        is_manager = bool(profile and profile.is_manager())
        rows.append(
            {
                "id": pointage.id,
                "employee_name": pointage.employe.get_full_name() or pointage.employe.username,
                "username": pointage.employe.username,
                "role": profile.role if profile else "",
                "role_label": "Manager" if is_manager else "Employé lavage",
                "clock_in_display": timezone.localtime(pointage.clock_in_time).strftime("%H:%M"),
                "clock_out_display": (
                    timezone.localtime(pointage.clock_out_time).strftime("%H:%M")
                    if pointage.clock_out_time
                    else ""
                ),
                "status_label": "Journée clôturée" if pointage.clock_out_time else "Présent, non clôturé",
                "daily_report_confirmed": pointage.daily_report_confirmed,
            }
        )
    return rows


def _capture_time_from_request(request, *, photo_field_name="photo"):
    photo = request.FILES.get(photo_field_name)
    if not photo:
        return None, None

    capture_time = extract_image_capture_datetime(photo)
    if capture_time:
        return photo, timezone.localtime(capture_time)

    last_modified_value = str(request.data.get("photo_last_modified", "")).strip()
    if not last_modified_value:
        return photo, None

    try:
        timestamp_ms = int(last_modified_value)
    except (TypeError, ValueError):
        return photo, None

    fallback_capture_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=dt_timezone.utc)
    return photo, timezone.localtime(fallback_capture_time)


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


class ManagerManualApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        settings = _first_manual_settings()
        machine_qs = ManagerManualMachine.objects.filter(is_active=True).order_by("display_order", "name")
        supplier_qs = ManagerManualSupplier.objects.filter(is_active=True).order_by("display_order", "name")
        machines = [_machine_payload(machine, request) for machine in machine_qs]
        suppliers = [_supplier_payload(supplier, request) for supplier in supplier_qs]
        if not machines:
            machines = [_default_machine_payload(item) for item in DEFAULT_MACHINE_CARDS]
        if not suppliers:
            suppliers = [_default_supplier_payload(item) for item in DEFAULT_SUPPLIER_CARDS]

        targets = {
            "daily": {
                "label": "Objectif quotidien",
                "value_fc": str(settings.daily_target_fc),
                "display": _fc_display(settings.daily_target_fc),
            },
            "weekly": {
                "label": "Objectif hebdomadaire",
                "value_fc": str(settings.weekly_target_fc),
                "display": _fc_display(settings.weekly_target_fc),
            },
            "monthly": {
                "label": "Objectif mensuel",
                "value_fc": str(settings.monthly_target_fc),
                "display": _fc_display(settings.monthly_target_fc),
            },
        }
        prices = [
            {"label": "Voiture", "display": _fc_display(settings.car_price_fc)},
            {"label": "Moto 2 roues", "display": _fc_display(settings.two_wheel_price_fc)},
            {"label": "Moto 3 roues", "display": _fc_display(settings.three_wheel_price_fc)},
        ]
        costs = [
            {"label": "Carburant", "display": _fc_display(settings.default_fuel_cost_fc)},
            {"label": "Eau", "display": _fc_display(settings.default_water_cost_fc)},
        ]
        sample_breakdown = [
            {"label": "4 voitures", "display": "80 000 FC"},
            {"label": "10 motos 2 roues", "display": "25 000 FC"},
            {"label": "5 motos 3 roues", "display": "25 000 FC"},
        ]
        icps = [
            {
                "label": "Volume",
                "value": "Nombre de véhicules lavés",
                "detail": "Suivre voitures, motos 2 roues et motos 3 roues chaque jour.",
            },
            {
                "label": "Présence",
                "value": "Ponctualité de l'équipe",
                "detail": "Contrôler retards, absences et sorties manquantes.",
            },
            {
                "label": "Qualité",
                "value": "Photos et satisfaction client",
                "detail": "Chaque lavage doit être traçable et proprement terminé.",
            },
            {
                "label": "Discipline",
                "value": "Rapport final envoyé",
                "detail": "Aucun achat, incident ou remarque importante ne doit rester hors système.",
            },
        ]

        sections = [
            DEFAULT_MANUAL_SECTIONS[0],
            DEFAULT_MANUAL_SECTIONS[1],
            {
                "id": "tarifs",
                "title": "Tarifs",
                "items": [
                    "Les tarifs ci-dessous sont éditables par l'administrateur.",
                    "Le manager applique les tarifs validés et signale toute situation spéciale.",
                ],
            },
            {
                "id": "objectifs",
                "title": "Objectifs quotidiens / hebdomadaires / mensuels",
                "items": [
                    f"Objectif quotidien: {_fc_display(settings.daily_target_fc)}.",
                    f"Objectif hebdomadaire: {_fc_display(settings.weekly_target_fc)}.",
                    f"Objectif mensuel: {_fc_display(settings.monthly_target_fc)}.",
                    "Exemple de composition: 4 voitures, 10 motos 2 roues et 5 motos 3 roues.",
                ],
            },
            DEFAULT_MANUAL_SECTIONS[2],
            {
                "id": "machines",
                "title": "Machines",
                "items": [
                    "Chaque machine doit être contrôlée avant le début du service.",
                    "Les photos et vidéos de formation peuvent être ajoutées par l'administrateur.",
                ],
            },
            {
                "id": "photos-equipements",
                "title": "Photos des équipements en fin de journée",
                "items": [
                    "Avant d'envoyer le rapport final, le manager doit prendre au moins une photo de chaque équipement actif.",
                    "Les photos prouvent que les machines sont présentes, rangées et dans l'état observé à la fermeture.",
                    "Si une machine manque, est cassée ou semble dangereuse, prendre la photo puis créer aussi un signalement de problème.",
                    "Ces photos sont envoyées automatiquement à l'administration avec le rapport final du jour.",
                ],
            },
            DEFAULT_MANUAL_SECTIONS[3],
            {
                "id": "fournisseurs",
                "title": "Fournisseurs",
                "items": [
                    "Utiliser uniquement les fournisseurs validés par l'administrateur.",
                    "Garder une trace claire des achats d'eau, carburant et consommables.",
                ],
            },
            *DEFAULT_MANUAL_SECTIONS[4:-1],
            {
                "id": "icps",
                "title": "Indicateurs Clés de Performance (ICP)",
                "items": [
                    "Les Indicateurs Clés de Performance (ICP) servent à piloter le site sans exposer les données financières sensibles au manager.",
                    "Le manager doit suivre le volume, la présence, la qualité, les incidents et les rapports avec des ICP simples.",
                ],
            },
            DEFAULT_MANUAL_SECTIONS[-1],
        ]

        return Response(
            {
                "title": "Manuel du Manager",
                "targets": targets,
                "prices": prices,
                "costs": costs,
                "sample_breakdown": sample_breakdown,
                "sections": sections,
                "machines": machines,
                "suppliers": suppliers,
                "checklist": next(section["items"] for section in sections if section["id"] == "checklist"),
                "icps": icps,
                "admin_note": (
                    "Les administrateurs peuvent modifier les paramètres, machines et fournisseurs "
                    "dans Django admin."
                ),
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
    permission_classes = [IsAuthenticated, IsPortalSelfAttendanceUser]

    def get(self, request):
        profile = _self_attendance_profile(request.user)
        today = timezone.localdate()
        shift_today = ShiftDay.objects.filter(employe=request.user, date=today).first()
        attendance_status = get_clock_in_status(
            today,
            shift_today.clock_in_time if shift_today else None,
        )
        clock_out_status = get_clock_out_status(
            today,
            shift_today.clock_out_time if shift_today else None,
        )

        return Response(
            {
                "today": today.isoformat(),
                "site": SiteSummarySerializer(profile.site).data,
                "shift_today": _safe_employee_shift(shift_today),
                "attendance_status": attendance_status,
                "clock_out_status": clock_out_status,
                "is_workday": is_workday(today),
                "schedule": attendance_schedule_context(),
                "can_clock_in": is_workday(today) and not bool(shift_today and shift_today.clock_in_time),
                "can_clock_out": is_workday(today) and bool(shift_today and shift_today.clock_in_time and not shift_today.clock_out_time),
            }
        )


class EmployeeClockInApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalSelfAttendanceUser]

    def post(self, request):
        user = request.user
        today = timezone.localdate()
        profile = _self_attendance_profile(user)
        if not is_workday(today):
            return Response(
                {"message": "La présence n'est requise que du lundi au samedi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_shift = ShiftDay.objects.filter(employe=user, date=today).first()
        if existing_shift and existing_shift.clock_in_time:
            return Response(
                {
                    "message": f"Vous avez déjà pointé l'entrée aujourd'hui à {timezone.localtime(existing_shift.clock_in_time):%H:%M}.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        site = profile.site

        photo, capture_time = _capture_time_from_request(request)
        if not photo:
            return Response(
                {"message": "Ajoutez une photo de début de journée pour enregistrer votre présence."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not capture_time:
            return Response(
                {"message": "La photo doit venir directement de la caméra du téléphone du jour. Heure de prise introuvable."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if timezone.localdate(capture_time) != today:
            return Response(
                {"message": "La photo de début doit avoir été prise aujourd'hui."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        shift.site = site
        shift.clock_in_time = capture_time
        shift.clock_in_photo = photo
        shift.clock_in_photo_taken_at = capture_time
        if lat is not None and lon is not None:
            shift.clock_in_gps_latitude = lat
            shift.clock_in_gps_longitude = lon
            shift.clock_in_gps_distance_mètres = gps_distance
        shift.clock_in_gps_status = gps_status
        shift.save()
        attendance_status = shift.get_clock_in_attendance_status()

        AuditLog.log(
            user=user,
            action="AUTRE",
            description=f"Pointage entrée: {shift} (GPS: {gps_status})",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        return Response(
            {
                "message": (
                    f"Début de journée enregistré à {timezone.localtime(shift.clock_in_time):%H:%M}."
                    f" Statut: {attendance_status['label'].lower()}."
                ),
                "shift_today": _safe_employee_shift(shift),
            }
        )


class EmployeeClockOutApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalSelfAttendanceUser]

    def post(self, request):
        user = request.user
        today = timezone.localdate()
        profile = _self_attendance_profile(user)
        if not is_workday(today):
            return Response(
                {"message": "La présence n'est requise que du lundi au samedi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

        site = profile.site

        photo, capture_time = _capture_time_from_request(request)
        if not photo:
            return Response(
                {"message": "Ajoutez une photo de fin de journée pour clôturer votre présence."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not capture_time:
            return Response(
                {"message": "La photo doit venir directement de la caméra du téléphone du jour. Heure de prise introuvable."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if timezone.localdate(capture_time) != today:
            return Response(
                {"message": "La photo de fin doit avoir été prise aujourd'hui."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if capture_time < shift.clock_in_time:
            return Response(
                {"message": "La photo de fin ne peut pas être antérieure au début de journée."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

        shift.clock_out_time = capture_time
        shift.clock_out_photo = photo
        shift.clock_out_photo_taken_at = capture_time
        if lat is not None and lon is not None:
            shift.clock_out_gps_latitude = lat
            shift.clock_out_gps_longitude = lon
            shift.clock_out_gps_distance_mètres = gps_distance
        shift.clock_out_gps_status = gps_status
        shift.save()
        clock_out_status = shift.get_clock_out_attendance_status()

        AuditLog.log(
            user=user,
            action="AUTRE",
            description=f"Pointage sortie: {shift} (GPS: {gps_status})",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        return Response(
            {
                "message": (
                    f"Fin de journée enregistrée à {timezone.localtime(shift.clock_out_time):%H:%M}."
                    f" Statut: {clock_out_status['label'].lower()}."
                ),
                "shift_today": _safe_employee_shift(shift),
            }
        )


class EmployeeCarWashListCreateApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        queryset = (
            request.user.lavages.select_related("site")
            .prefetch_related(PHOTO_COUNT_PREFETCH)
            .order_by("-created_at")
        )
        return _paginate(
            self,
            queryset,
            EmployeeCarWashSerializer,
            request,
            page_size=12,
            serializer_context=LAVAGE_LIST_SERIALIZER_CONTEXT,
        )

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
            .prefetch_related(PHOTO_COUNT_PREFETCH)
            .order_by("-created_at")
        )
        today_issues = IssueReport.objects.filter(
            employe=user,
            site=profile.site,
            created_at__date=today,
        ).order_by("-created_at")
        total_washes = today_washes.count()
        total_issues = today_issues.count()

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
                "computed_total_washes": total_washes,
                "today_washes": EmployeeCarWashSerializer(
                    today_washes[:REPORT_PREVIEW_LIMIT],
                    many=True,
                    context={"request": request, **LAVAGE_LIST_SERIALIZER_CONTEXT},
                ).data,
                "today_issues": EmployeeIssueSerializer(today_issues[:REPORT_PREVIEW_LIMIT], many=True, context={"request": request}).data,
                "today_washes_truncated": total_washes > REPORT_PREVIEW_LIMIT,
                "today_issues_truncated": total_issues > REPORT_PREVIEW_LIMIT,
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

        try:
            amount_fc = _parse_required_fuel_purchase_amount(request.data.get("amount_fc"))
        except ValueError as exc:
            return Response(
                {
                    "message": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        reporter_name = request.user.get_full_name() or request.user.username
        purchase = SiteFuelPurchase.objects.create(
            site=profile.site,
            billing_month=billing_month,
            purchase_date=today,
            amount_fc=amount_fc,
            notes=f"Signalé via portail employé par {reporter_name}.",
            created_by=request.user,
        )
        _send_fuel_purchase_notification(purchase)
        AuditLog.log(
            user=request.user,
            action="AUTRE",
            description=(
                f"Achat de carburant signalé via portail employé: "
                f"{profile.site.nom} - {purchase.purchase_date} - {_fc_display(amount_fc)}"
            ),
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return Response(
            {
                "message": f"Achat de carburant enregistré pour aujourd'hui ({_fc_display(amount_fc)}).",
                "purchase": EmployeeFuelPurchaseSerializer(purchase).data,
            },
            status=status.HTTP_201_CREATED,
        )


class EmployeeHistorySummaryApi(APIView):
    permission_classes = [IsAuthenticated, IsPortalEmployee]

    def get(self, request):
        profile = _employee_profile(request.user)
        today = timezone.localdate()
        cache_key = f"portal_api:employee_history_summary:user:{request.user.pk}:month:{today:%Y-%m}"
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            return Response(cached_payload)

        month_start = today.replace(day=1)
        payload = {
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
                    billing_month=month_start,
                ).count(),
                "carburant_mois": SiteFuelPurchase.objects.filter(
                    site=profile.site,
                    billing_month=month_start,
                ).count(),
            },
            "cache_ttl_seconds": PORTAL_SUMMARY_CACHE_SECONDS,
        }
        cache.set(cache_key, payload, PORTAL_SUMMARY_CACHE_SECONDS)
        return Response(payload)


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
        cache_key = (
            "portal_api:manager_dashboard:"
            f"user:{request.user.pk}:start:{start_date.isoformat()}:end:{end_date.isoformat()}"
            f":money:{int(_can_view_manager_money(request.user))}"
        )
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            return Response(cached_payload)

        sites = list(_manager_accessible_sites(request.user))
        site_ids = [site.id for site in sites]
        can_view_money = _can_view_manager_money(request.user)

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
        wash_annotations = {"total_lavages": Count("id")}
        if can_view_money:
            wash_annotations["chiffre_jour"] = Sum("montant")
        wash_stats = {
            item["site"]: item
            for item in CarWash.objects.filter(
                site_id__in=site_ids,
                date__gte=start_date,
                date__lte=end_date,
            ).values("site").annotate(**wash_annotations)
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
            card = {
                "site_id": str(site.id),
                "site_name": site.nom,
                "total_employes": total_employes,
                "presents": presents,
                "absents": max(total_employes - presents, 0),
                "missed_punch": pointage_summary.get("missed_punch", 0),
                "total_lavages": wash_summary.get("total_lavages", 0),
                "problemes_ouverts": issue_stats.get(site.id, 0),
            }
            if can_view_money:
                card["revenue_fc"] = str(wash_summary.get("chiffre_jour") or 0)
                card["revenue_display"] = _fc_display(wash_summary.get("chiffre_jour") or 0)
            cards.append(card)

        payload = {
            "today": today.isoformat(),
            "date_debut": date_debut,
            "date_fin": date_fin,
            "selected_period_label": selected_period_label,
            "sites": cards,
            "available_sites": _site_options(sites),
            "can_view_money": can_view_money,
            "cache_ttl_seconds": MANAGER_DASHBOARD_CACHE_SECONDS,
        }
        cache.set(cache_key, payload, MANAGER_DASHBOARD_CACHE_SECONDS)
        return Response(payload)


class ManagerPointageListApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        accessible_sites = list(_manager_accessible_sites(request.user))
        site_ids = [site.id for site in accessible_sites]
        selected_site, _accessible_sites = _manager_selected_site(request.user, request)
        try:
            team_date = _parse_portal_date(request.query_params.get("team_date"))
        except ValueError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        visible_roles = _manager_visible_staff_roles(request.user)
        queryset = (
            ShiftDay.objects.select_related("employe", "site", "corrected_by")
            .filter(site_id__in=site_ids, employe__userprofile__role__in=visible_roles)
            .order_by("-date", "-clock_in_time")
        )

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
                    "employees": _employee_options_for_sites(site_ids, request.user),
                },
                "today": timezone.localdate().isoformat(),
                "team_date": team_date.isoformat(),
                "schedule": attendance_schedule_context(),
                "selected_team_site": SiteSummarySerializer(selected_site).data if selected_site else None,
                "team_attendance": (
                    _manager_team_attendance_rows(selected_site, team_date, request)
                    if selected_site else []
                ),
                "can_correct_time": _can_view_manager_money(request.user),
            },
        )


class ManagerTeamAttendanceApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request):
        site, _accessible_sites = _manager_selected_site(request.user, request)
        if not site:
            return Response({"message": "Aucun site manager accessible."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_date = _parse_portal_date(request.data.get("date"))
            target_time = _parse_portal_time(target_date, request.data.get("time"))
        except ValueError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if target_date > timezone.localdate():
            return Response({"message": "Impossible de pointer une date future."}, status=status.HTTP_400_BAD_REQUEST)

        action = str(request.data.get("action", "")).strip()
        if action not in {"clock_in", "clock_out"}:
            return Response({"message": "Action de pointage invalide."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            employee_id = int(request.data.get("employee_id"))
        except (TypeError, ValueError):
            return Response({"message": "Employé invalide."}, status=status.HTTP_400_BAD_REQUEST)

        employee = get_object_or_404(
            User.objects.select_related("userprofile"),
            pk=employee_id,
            userprofile__site=site,
            userprofile__role=UserProfile.EMPLOYEE_ROLE,
            userprofile__actif=True,
        )

        with transaction.atomic():
            shift, _created = ShiftDay.objects.select_for_update().get_or_create(
                employe=employee,
                date=target_date,
                defaults={"site": site},
            )
            if shift.site_id != site.id:
                return Response({"message": "Cet employé n'appartient pas à ce site."}, status=status.HTTP_403_FORBIDDEN)

            before = {
                "clock_in_time": str(shift.clock_in_time) if shift.clock_in_time else None,
                "clock_out_time": str(shift.clock_out_time) if shift.clock_out_time else None,
            }

            if action == "clock_in":
                if shift.clock_in_time and not _can_view_manager_money(request.user):
                    return Response(
                        {"message": "L'arrivée existe déjà. Seul l'administrateur peut corriger l'heure."},
                        status=status.HTTP_409_CONFLICT,
                    )
                shift.clock_in_time = target_time
                message = "Heure d'arrivée enregistrée."
            else:
                if not shift.clock_in_time:
                    return Response(
                        {"message": "Enregistrez d'abord l'heure d'arrivée de cet employé."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if target_time < shift.clock_in_time:
                    return Response(
                        {"message": "L'heure de fin ne peut pas être avant l'arrivée."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if shift.clock_out_time and not _can_view_manager_money(request.user):
                    return Response(
                        {"message": "La fin de journée existe déjà. Seul l'administrateur peut corriger l'heure."},
                        status=status.HTTP_409_CONFLICT,
                    )
                shift.clock_out_time = target_time
                message = "Heure de fin enregistrée."

            manager_name = request.user.get_full_name() or request.user.username
            shift.corrected_by = request.user
            shift.correction_reason = f"Pointage équipe saisi par le manager {manager_name}."
            shift.corrected_at = timezone.now()
            shift.save()

        AuditLog.log(
            user=request.user,
            action="CORRIGER_POINTAGE",
            description=f"Pointage équipe saisi par manager: {employee.get_full_name() or employee.username} - {target_date}",
            motif=shift.correction_reason,
            content_object=shift,
            donnees_avant=before,
            donnees_apres={
                "clock_in_time": str(shift.clock_in_time) if shift.clock_in_time else None,
                "clock_out_time": str(shift.clock_out_time) if shift.clock_out_time else None,
            },
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        return Response(
            {
                "message": message,
                "pointage": ShiftDaySerializer(shift, context={"request": request}).data,
            },
            status=status.HTTP_200_OK,
        )


class ManagerPointageCorrectionApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, pointage_id):
        if not _can_view_manager_money(request.user):
            return Response(
                {"message": "Seul l'administrateur peut corriger les heures de pointage."},
                status=status.HTTP_403_FORBIDDEN,
            )

        accessible_site_ids = {site.id for site in _manager_accessible_sites(request.user)}
        visible_roles = _manager_visible_staff_roles(request.user)
        pointage = get_object_or_404(
            ShiftDay.objects.select_related("site", "employe"),
            id=pointage_id,
            site_id__in=accessible_site_ids,
            employe__userprofile__role__in=visible_roles,
        )
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
        visible_roles = _manager_visible_staff_roles(request.user)
        pointage = get_object_or_404(
            ShiftDay.objects.select_related("site", "employe", "corrected_by"),
            id=pointage_id,
            site_id__in=accessible_site_ids,
            employe__userprofile__role__in=visible_roles,
        )
        return Response(ShiftDaySerializer(pointage).data)


class ManagerDailyReportApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        site, accessible_sites = _manager_selected_site(request.user, request)
        if not site:
            return Response({"message": "Aucun site manager accessible."}, status=status.HTTP_400_BAD_REQUEST)

        report_date = timezone.localdate()
        date_value = request.query_params.get("date")
        if date_value:
            try:
                report_date = datetime.strptime(date_value, "%Y-%m-%d").date()
            except ValueError:
                return Response({"message": "Date invalide."}, status=status.HTTP_400_BAD_REQUEST)

        report = ShiftDay.objects.filter(employe=request.user, site=site, date=report_date).first()
        expense_shift = report or ShiftDay(employe=request.user, site=site, date=report_date)
        today_washes = (
            CarWash.objects.filter(site=site, date=report_date)
            .select_related("employe", "site")
            .prefetch_related(PHOTO_COUNT_PREFETCH)
            .order_by("-created_at")
        )
        today_issues = (
            IssueReport.objects.filter(site=site, created_at__date=report_date)
            .select_related("employe", "site", "traite_par")
            .order_by("-created_at")
        )
        total_washes = today_washes.count()
        issue_count = today_issues.count()
        water_purchase_today = (
            SiteWaterPurchase.objects.filter(site=site, purchase_date=report_date)
            .select_related("created_by", "supplier")
            .order_by("-created_at")
            .first()
        )
        fuel_purchase_today = (
            SiteFuelPurchase.objects.filter(site=site, purchase_date=report_date)
            .select_related("created_by")
            .order_by("-created_at")
            .first()
        )
        attendance_rows = _manager_report_attendance_rows(site, report_date)
        equipment_machines = list(ManagerManualMachine.objects.filter(is_active=True).order_by("display_order", "name"))

        return Response(
            {
                "date": report_date.isoformat(),
                "site": SiteSummarySerializer(site).data,
                "available_sites": _site_options(accessible_sites),
                "total_lavages": total_washes,
                "issue_count": issue_count,
                "report_submitted": bool(report and report.daily_report_confirmed),
                "report_notes": report.report_notes if report else "",
                "shift": _safe_employee_shift(report) if report else None,
                "submitted_total_amount": (
                    f"{Decimal(report.total_amount_reported_fc or 0):.2f}"
                    if report and report.daily_report_confirmed else ""
                ),
                "expense_form": _build_initial_daily_expense_form(expense_shift),
                "submitted_total_lavages": report.total_lavages_reported if report and report.daily_report_confirmed else total_washes,
                "attendance_rows": attendance_rows,
                "attendance_count": len(attendance_rows),
                "today_washes": ManagerCarWashSerializer(
                    today_washes[:REPORT_PREVIEW_LIMIT],
                    many=True,
                    context={"request": request, "can_view_money": False, **LAVAGE_LIST_SERIALIZER_CONTEXT},
                ).data,
                "today_issues": ManagerIssueSerializer(today_issues[:REPORT_PREVIEW_LIMIT], many=True, context={"request": request}).data,
                "today_washes_truncated": total_washes > REPORT_PREVIEW_LIMIT,
                "today_issues_truncated": issue_count > REPORT_PREVIEW_LIMIT,
                "water_purchase_today": EmployeeWaterPurchaseSerializer(water_purchase_today).data if water_purchase_today else None,
                "fuel_purchase_today": EmployeeFuelPurchaseSerializer(fuel_purchase_today).data if fuel_purchase_today else None,
                "equipment_checklist": _manager_equipment_checklist(equipment_machines, report, request),
                "equipment_required": bool(equipment_machines),
                "can_view_money": False,
            }
        )

    def post(self, request):
        site, _accessible_sites = _manager_selected_site(request.user, request)
        if not site:
            return Response({"message": "Aucun site manager accessible."}, status=status.HTTP_400_BAD_REQUEST)

        report_date = timezone.localdate()
        date_value = str(request.data.get("date", "")).strip()
        if date_value:
            try:
                report_date = datetime.strptime(date_value, "%Y-%m-%d").date()
            except ValueError:
                return Response({"message": "Date invalide."}, status=status.HTTP_400_BAD_REQUEST)

        notes = str(request.data.get("notes", "")).strip()
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
            return Response(
                {"message": expense_form["errors"][0], "errors": expense_form["errors"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        equipment_machines = list(ManagerManualMachine.objects.filter(is_active=True).order_by("display_order", "name"))
        equipment_photo_files = request.FILES.getlist("equipment_photo")
        equipment_machine_ids = request.data.getlist("equipment_photo_machine_id")
        equipment_machine_map = {str(machine.pk): machine for machine in equipment_machines}
        equipment_errors = []
        uploaded_equipment_machine_ids = set()

        if len(equipment_photo_files) != len(equipment_machine_ids):
            equipment_errors.append("Chaque photo d'équipement doit être associée à une machine.")

        for machine_id, photo in zip(equipment_machine_ids, equipment_photo_files):
            machine_id = str(machine_id).strip()
            if machine_id not in equipment_machine_map:
                equipment_errors.append("Machine invalide dans les photos d'équipement.")
                continue
            content_type = getattr(photo, "content_type", "")
            if content_type and not content_type.startswith("image/"):
                equipment_errors.append("Les fichiers des équipements doivent être des images.")
                continue
            uploaded_equipment_machine_ids.add(machine_id)

        if _is_location_manager(request.user):
            missing_machines = [
                machine.name
                for machine in equipment_machines
                if str(machine.pk) not in uploaded_equipment_machine_ids
            ]
            if missing_machines:
                equipment_errors.append(
                    "Ajoutez au moins une photo de fin de journée pour: "
                    + ", ".join(missing_machines)
                    + "."
                )

        if equipment_errors:
            return Response(
                {"message": equipment_errors[0], "errors": equipment_errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        total_washes = CarWash.objects.filter(site=site, date=report_date).count()
        issue_count = IssueReport.objects.filter(site=site, created_at__date=report_date).count()
        with transaction.atomic():
            Location.objects.select_for_update().get(pk=site.pk)
            report, _created = (
                ShiftDay.objects.select_for_update()
                .get_or_create(
                    employe=request.user,
                    date=report_date,
                    defaults={"site": site},
                )
            )
            was_update = report.daily_report_confirmed
            if was_update and _is_location_manager(request.user):
                return Response(
                    {
                        "message": (
                            "Le rapport final du jour a déjà été envoyé. "
                            "Contactez l'administrateur pour une correction."
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            report.site = site
            report.total_lavages_reported = total_washes
            report.total_amount_reported_fc = total_amount_reported
            report.daily_expenses = expense_form["items"]
            report.daily_expenses_total_fc = expense_form["total"]
            report.report_notes = notes
            report.daily_report_confirmed = True
            report.save()
            if equipment_photo_files:
                ManagerEquipmentPhoto.objects.filter(daily_report=report).delete()
                for machine_id, photo in zip(equipment_machine_ids, equipment_photo_files):
                    machine = equipment_machine_map[str(machine_id).strip()]
                    ManagerEquipmentPhoto.objects.create(
                        daily_report=report,
                        machine=machine,
                        machine_name=machine.name,
                        photo=photo,
                        uploaded_by=request.user,
                        captured_at=extract_image_capture_datetime(photo),
                    )

        sync_site_finance_from_daily_reports(site, report_date, actor=request.user)
        _send_final_report_notification(
            shift=report,
            computed_total_amount=total_amount_reported,
            issue_count=issue_count,
            was_update=was_update,
        )
        AuditLog.log(
            user=request.user,
            action="AUTRE",
            description=f"Rapport journalier manager {'mis à jour' if was_update else 'enregistré'}: {site.nom} - {report_date}",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return Response(
            {
                "message": "Rapport manager mis à jour avec succès." if was_update else "Rapport manager envoyé avec succès.",
                "total_lavages": total_washes,
                "issue_count": issue_count,
            }
        )


class ManagerCarWashListApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        accessible_sites = list(_manager_accessible_sites(request.user))
        site_ids = [site.id for site in accessible_sites]
        queryset = (
            CarWash.objects.select_related("employe", "site")
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

        can_view_money = _can_view_manager_money(request.user)
        include_image_previews = can_view_money
        if include_image_previews:
            queryset = queryset.prefetch_related(PHOTO_PREFETCH)
        else:
            queryset = queryset.prefetch_related(PHOTO_COUNT_PREFETCH)
        if can_view_money:
            aggregate_totals = queryset.aggregate(total=Sum("montant"), count=Count("id"))
            total_montant = aggregate_totals["total"] or Decimal("0")
            total_count = aggregate_totals["count"] or 0
        else:
            total_montant = Decimal("0")
            total_count = queryset.count()

        return _paginate(
            self,
            queryset,
            ManagerCarWashSerializer,
            request,
            page_size=20,
            serializer_context={
                "can_view_money": can_view_money,
                **LAVAGE_LIST_SERIALIZER_CONTEXT,
                "include_image_previews": include_image_previews,
            },
            extra={
                "totals": {
                    "count": total_count,
                    **(
                        {
                            "amount_fc": str(total_montant),
                            "amount_display": _fc_display(total_montant),
                        }
                        if can_view_money else {}
                    ),
                },
                "filters": {
                    "sites": _site_options(accessible_sites),
                    "employees": _employee_options_for_sites(site_ids, request.user),
                    "types_service": [
                        {"value": value, "label": label}
                        for value, label in CarWash.TYPE_SERVICE_CHOICES
                    ],
                },
                "can_view_money": can_view_money,
            },
        )

    def post(self, request):
        site, _accessible_sites = _manager_selected_site(request.user, request)
        if not site:
            return Response({"message": "Aucun site manager accessible."}, status=status.HTTP_400_BAD_REQUEST)

        type_service = str(request.data.get("type_service", "")).strip()
        plaque = str(request.data.get("plaque", "")).strip().upper()
        notes = str(request.data.get("notes", "")).strip()
        plaque_photo = request.FILES.get("plaque_photo")
        photos = request.FILES.getlist("photos")

        valid_service_types = {choice[0] for choice in CarWash.TYPE_SERVICE_CHOICES}
        if type_service not in valid_service_types:
            return Response({"message": "Type de service invalide."}, status=status.HTTP_400_BAD_REQUEST)
        if not photos:
            return Response({"message": "Au moins une photo est requise."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            duplicate_window_start = timezone.now() - timedelta(seconds=45)
            duplicate_qs = CarWash.objects.filter(
                employe=request.user,
                site=site,
                date=timezone.localdate(),
                type_service=type_service,
                plaque=plaque,
                montant=Decimal("0"),
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
                site=site,
                date=timezone.localdate(),
                type_service=type_service,
                plaque=plaque,
                plaque_photo=plaque_photo,
                montant=Decimal("0"),
                notes=notes,
            )
            for photo in photos:
                CarWashPhoto.objects.create(lavage=lavage, photo=photo, type_photo="APRES")

        AuditLog.log(
            user=request.user,
            action="CREER",
            description=f"Nouveau lavage enregistré par manager: {lavage}",
            content_object=lavage,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        sync_site_finance_from_daily_reports(site, lavage.date, actor=request.user)

        lavage = (
            CarWash.objects.select_related("site", "employe")
            .annotate(photo_count_value=Count("photos", distinct=True))
            .prefetch_related(PHOTO_PREFETCH)
            .get(pk=lavage.pk)
        )
        return Response(
            {
                "message": "Lavage enregistré avec succès.",
                "lavage": ManagerCarWashSerializer(
                    lavage,
                    context={"request": request, "can_view_money": False},
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )


class ManagerWaterPurchaseApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        site, _accessible_sites = _manager_selected_site(request.user, request)
        if not site:
            return Response({"message": "Aucun site manager accessible."}, status=status.HTTP_400_BAD_REQUEST)

        today = timezone.localdate()
        billing_month = today.replace(day=1)
        today_purchase = (
            SiteWaterPurchase.objects.filter(site=site, purchase_date=today)
            .select_related("created_by", "supplier")
            .order_by("-created_at")
            .first()
        )
        month_purchases_qs = (
            SiteWaterPurchase.objects.filter(site=site, billing_month=billing_month)
            .select_related("created_by", "supplier")
            .order_by("-purchase_date", "-created_at")
        )
        last_purchase = month_purchases_qs.first()
        default_supplier = get_default_water_supplier()

        return Response(
            {
                "today": today.isoformat(),
                "site": SiteSummarySerializer(site).data,
                "billing_month": billing_month.isoformat(),
                "billing_month_display": billing_month.strftime("%m/%Y"),
                "default_supplier_name": default_supplier.name,
                "supplier_options": _manager_water_supplier_options(),
                "today_purchase": EmployeeWaterPurchaseSerializer(today_purchase).data if today_purchase else None,
                "month_purchase_count": month_purchases_qs.count(),
                "last_purchase": EmployeeWaterPurchaseSerializer(last_purchase).data if last_purchase else None,
            }
        )

    def post(self, request):
        site, _accessible_sites = _manager_selected_site(request.user, request)
        if not site:
            return Response({"message": "Aucun site manager accessible."}, status=status.HTTP_400_BAD_REQUEST)

        today = timezone.localdate()
        billing_month = today.replace(day=1)
        try:
            selected_supplier, selected_amount = _parse_manager_water_supplier(request.data, billing_month)
        except ValueError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        reporter_name = request.user.get_full_name() or request.user.username
        with transaction.atomic():
            Location.objects.select_for_update().get(pk=site.pk)
            if SiteWaterPurchase.objects.filter(site=site, purchase_date=today).exists():
                return Response(
                    {
                        "message": (
                            "L'achat d'eau du jour a déjà été signalé. "
                            "L'administrateur peut le corriger si nécessaire."
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            purchase = SiteWaterPurchase.objects.create(
                site=site,
                supplier=selected_supplier,
                billing_month=billing_month,
                purchase_date=today,
                amount_fc=selected_amount,
                notes=f"Signalé via portail manager par {reporter_name}. Fournisseur: {selected_supplier.name}.",
                created_by=request.user,
            )
        _send_water_purchase_notification(purchase)
        AuditLog.log(
            user=request.user,
            action="AUTRE",
            description=f"Achat d'eau signalé via portail manager: {site.nom} - {selected_supplier.name} - {purchase.purchase_date}",
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


class ManagerFuelPurchaseApi(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        site, _accessible_sites = _manager_selected_site(request.user, request)
        if not site:
            return Response({"message": "Aucun site manager accessible."}, status=status.HTTP_400_BAD_REQUEST)

        today = timezone.localdate()
        billing_month = today.replace(day=1)
        today_purchase = (
            SiteFuelPurchase.objects.filter(site=site, purchase_date=today)
            .select_related("created_by")
            .order_by("-created_at")
            .first()
        )
        month_purchases_qs = (
            SiteFuelPurchase.objects.filter(site=site, billing_month=billing_month)
            .select_related("created_by")
            .order_by("-purchase_date", "-created_at")
        )
        last_purchase = month_purchases_qs.first()

        return Response(
            {
                "today": today.isoformat(),
                "site": SiteSummarySerializer(site).data,
                "billing_month": billing_month.isoformat(),
                "billing_month_display": billing_month.strftime("%m/%Y"),
                "today_purchase": EmployeeFuelPurchaseSerializer(today_purchase).data if today_purchase else None,
                "month_purchase_count": month_purchases_qs.count(),
                "last_purchase": EmployeeFuelPurchaseSerializer(last_purchase).data if last_purchase else None,
            }
        )

    def post(self, request):
        site, _accessible_sites = _manager_selected_site(request.user, request)
        if not site:
            return Response({"message": "Aucun site manager accessible."}, status=status.HTTP_400_BAD_REQUEST)

        today = timezone.localdate()
        billing_month = today.replace(day=1)
        try:
            amount_fc = _parse_required_fuel_purchase_amount(request.data.get("amount_fc"))
        except ValueError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        reporter_name = request.user.get_full_name() or request.user.username
        with transaction.atomic():
            Location.objects.select_for_update().get(pk=site.pk)
            if SiteFuelPurchase.objects.filter(site=site, purchase_date=today).exists():
                return Response(
                    {
                        "message": (
                            "L'achat de carburant du jour a déjà été signalé. "
                            "L'administrateur peut le corriger si nécessaire."
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            purchase = SiteFuelPurchase.objects.create(
                site=site,
                billing_month=billing_month,
                purchase_date=today,
                amount_fc=amount_fc,
                notes=f"Signalé via portail manager par {reporter_name}.",
                created_by=request.user,
            )
        _send_fuel_purchase_notification(purchase)
        AuditLog.log(
            user=request.user,
            action="AUTRE",
            description=f"Achat de carburant signalé via portail manager: {site.nom} - {purchase.purchase_date}",
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

    def post(self, request):
        site, _accessible_sites = _manager_selected_site(request.user, request)
        if not site:
            return Response({"message": "Aucun site manager accessible."}, status=status.HTTP_400_BAD_REQUEST)

        categorie = str(request.data.get("categorie", "")).strip()
        description = str(request.data.get("description", "")).strip()
        photo = request.FILES.get("photo")

        if categorie not in {choice[0] for choice in IssueReport.CATEGORIE_CHOICES}:
            return Response({"message": "Catégorie invalide."}, status=status.HTTP_400_BAD_REQUEST)
        if not description:
            return Response({"message": "La description est requise."}, status=status.HTTP_400_BAD_REQUEST)

        probleme = IssueReport.objects.create(
            employe=request.user,
            site=site,
            categorie=categorie,
            description=description,
            photo=photo,
            statut="OUVERT",
        )
        _send_issue_report_notification(probleme)
        AuditLog.log(
            user=request.user,
            action="CREER",
            description=f"Nouveau problème signalé par manager: {probleme.get_categorie_display()}",
            content_object=probleme,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return Response(
            {
                "message": "Problème signalé avec succès.",
                "probleme": ManagerIssueSerializer(probleme, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
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
