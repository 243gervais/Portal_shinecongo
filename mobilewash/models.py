from datetime import timedelta
from decimal import Decimal
import os

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from audit.models import AuditLog
from .validators import validate_mobile_file, validate_mobile_image


USD = "USD"
STANDARD_PRICE = Decimal("30.00")
SERVICE_COMPONENT = Decimal("20.00")
LOGISTICS_COMPONENT = Decimal("10.00")


def _dated_upload_path(prefix, instance, filename):
    today = timezone.localdate()
    base, ext = os.path.splitext(filename or "")
    safe_ext = ext.lower() or ".jpg"
    obj_id = getattr(instance, "work_order_id", None) or getattr(instance, "id", "new")
    return f"mobilewash/{prefix}/{today:%Y/%m/%d}/{obj_id}/{base[:80]}{safe_ext}"


def signed_contract_upload_path(instance, filename):
    return _dated_upload_path("contracts", instance, filename)


def signature_upload_path(instance, filename):
    return _dated_upload_path("signatures", instance, filename)


def proof_upload_path(instance, filename):
    return _dated_upload_path("proofs", instance, filename)


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Cree le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifie le")

    class Meta:
        abstract = True


class CorporateCompany(TimestampedModel):
    legal_name = models.CharField(max_length=220, verbose_name="Raison sociale")
    trading_name = models.CharField(max_length=220, blank=True, verbose_name="Nom commercial")
    address = models.TextField(blank=True, verbose_name="Adresse")
    commune = models.CharField(max_length=120, blank=True, verbose_name="Commune")
    city = models.CharField(max_length=120, default="Kinshasa", verbose_name="Ville")
    rccm = models.CharField(max_length=80, blank=True, verbose_name="RCCM")
    tax_number = models.CharField(max_length=80, blank=True, verbose_name="Numero d'impot")
    id_nat = models.CharField(max_length=80, blank=True, verbose_name="ID NAT")
    billing_email = models.EmailField(blank=True, verbose_name="Email facturation")
    telephone = models.CharField(max_length=40, blank=True, verbose_name="Telephone")
    default_payment_terms_days = models.PositiveSmallIntegerField(default=30, verbose_name="Delai paiement")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    internal_notes = models.TextField(blank=True, verbose_name="Notes internes")

    class Meta:
        verbose_name = "Entreprise corporate"
        verbose_name_plural = "Entreprises corporate"
        ordering = ["legal_name"]
        indexes = [
            models.Index(fields=["is_active", "legal_name"]),
            models.Index(fields=["city", "commune"]),
        ]

    def __str__(self):
        return self.trading_name or self.legal_name


class CorporateContact(TimestampedModel):
    ROLE_CHOICES = [
        ("PRIMARY", "Contact principal"),
        ("OPS", "Contact operationnel"),
        ("AP", "Comptabilite fournisseur"),
        ("OTHER", "Autre"),
    ]

    company = models.ForeignKey(CorporateCompany, on_delete=models.CASCADE, related_name="contacts")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="OTHER", verbose_name="Role")
    full_name = models.CharField(max_length=160, verbose_name="Nom complet")
    title = models.CharField(max_length=120, blank=True, verbose_name="Fonction")
    telephone = models.CharField(max_length=40, blank=True, verbose_name="Telephone")
    email = models.EmailField(blank=True, verbose_name="Email")
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Contact corporate"
        verbose_name_plural = "Contacts corporate"
        ordering = ["company", "role", "full_name"]
        indexes = [models.Index(fields=["company", "role", "is_active"])]

    def __str__(self):
        return f"{self.full_name} - {self.company}"


class MobileEmployeeProfile(TimestampedModel):
    ROLE_CHOICES = [
        ("MANAGER", "Manager"),
        ("LEAD_WASHER", "Chef laveur"),
        ("MOBILE_WASHER", "Laveur mobile"),
        ("SUPPORT_WASHER", "Support laveur"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mobilewash_profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="MOBILE_WASHER")
    telephone = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    quality_issues = models.PositiveIntegerField(default=0)
    rewash_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Employe lavage mobile"
        verbose_name_plural = "Employes lavage mobile"
        indexes = [models.Index(fields=["role", "is_active"])]

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Contract(TimestampedModel):
    STATUS_CHOICES = [
        ("DRAFT", "Brouillon"),
        ("SENT", "Envoye"),
        ("NEGOTIATING", "Negociation"),
        ("ACTIVE", "Actif"),
        ("SUSPENDED", "Suspendu"),
        ("EXPIRED", "Expire"),
        ("TERMINATED", "Termine"),
    ]
    BILLING_FREQUENCY_CHOICES = [("MONTHLY", "Mensuelle")]
    SERVICE_TYPE_CHOICES = [
        ("STANDARD", "Lavage standard"),
        ("EXTERIOR", "Exterieur"),
        ("COMPLETE", "Complet"),
    ]

    contract_number = models.CharField(max_length=40, unique=True, verbose_name="Numero contrat")
    company = models.ForeignKey(CorporateCompany, on_delete=models.PROTECT, related_name="contracts")
    title = models.CharField(max_length=220, verbose_name="Titre")
    start_date = models.DateField(verbose_name="Date debut")
    end_date = models.DateField(null=True, blank=True, verbose_name="Date fin")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT", db_index=True)
    billing_frequency = models.CharField(max_length=20, choices=BILLING_FREQUENCY_CHOICES, default="MONTHLY")
    currency = models.CharField(max_length=3, default=USD)
    monthly_package_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("360.00"), validators=[MinValueValidator(0)])
    included_washes_per_month = models.PositiveIntegerField(default=12)
    included_visits_per_month = models.PositiveIntegerField(default=0)
    additional_wash_price = models.DecimalField(max_digits=10, decimal_places=2, default=STANDARD_PRICE, validators=[MinValueValidator(0)])
    minimum_vehicles_per_intervention = models.PositiveIntegerField(default=1)
    minimum_intervention_charge = models.DecimalField(max_digits=10, decimal_places=2, default=STANDARD_PRICE, validators=[MinValueValidator(0)])
    payment_terms_days = models.PositiveSmallIntegerField(default=30)
    service_location = models.TextField(verbose_name="Lieu de service")
    default_service_type = models.CharField(max_length=20, choices=SERVICE_TYPE_CHOICES, default="STANDARD")
    default_team_size = models.PositiveSmallIntegerField(default=2)
    client_obligations = models.TextField(blank=True)
    shine_obligations = models.TextField(blank=True)
    cancellation_notice = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    signed_contract_file = models.FileField(upload_to=signed_contract_upload_path, validators=[validate_mobile_file], null=True, blank=True)
    signed_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="mobile_contracts_created")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="mobile_contracts_approved")

    class Meta:
        verbose_name = "Contrat mobile"
        verbose_name_plural = "Contrats mobiles"
        ordering = ["-start_date", "contract_number"]
        permissions = [
            ("view_mobile_financials", "Voir les donnees financieres lavage mobile"),
            ("approve_mobile_contract", "Approuver les contrats lavage mobile"),
            ("override_workorder_review", "Finaliser un ordre sans revue manager"),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["status", "start_date"]),
            models.Index(fields=["contract_number"]),
        ]

    def __str__(self):
        return f"{self.contract_number} - {self.company}"

    def clean(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "La date de fin ne peut pas preceder la date de debut."})

    def usage_for_period(self, period_start, period_end):
        completed_orders = self.work_orders.filter(
            scheduled_start__date__gte=period_start,
            scheduled_start__date__lte=period_end,
            status=WorkOrder.STATUS_COMPLETED,
            client_confirmed_at__isnull=False,
        )
        used_visits = completed_orders.count()
        used_washes = WorkOrderVehicle.objects.filter(
            work_order__in=completed_orders,
            status=WorkOrderVehicle.STATUS_COMPLETED,
        ).count()
        included_washes = self.included_washes_per_month
        included_visits = self.included_visits_per_month
        return {
            "included_washes": included_washes,
            "used_washes": used_washes,
            "remaining_washes": max(included_washes - used_washes, 0),
            "included_visits": included_visits,
            "used_visits": used_visits,
            "remaining_visits": max(included_visits - used_visits, 0) if included_visits else None,
            "billable_additional_washes": max(used_washes - included_washes, 0),
            "billable_additional_visits": max(used_visits - included_visits, 0) if included_visits else 0,
            "allowance_exceeded": used_washes > included_washes or (included_visits and used_visits > included_visits),
        }


class Vehicle(TimestampedModel):
    company = models.ForeignKey(CorporateCompany, on_delete=models.CASCADE, related_name="vehicles")
    internal_fleet_number = models.CharField(max_length=80, blank=True)
    license_plate = models.CharField(max_length=60, blank=True)
    vehicle_type = models.CharField(max_length=80, blank=True)
    make = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=80, blank=True)
    color = models.CharField(max_length=60, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Vehicule corporate"
        verbose_name_plural = "Vehicules corporate"
        ordering = ["company", "license_plate", "internal_fleet_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "license_plate"],
                condition=Q(is_active=True) & ~Q(license_plate=""),
                name="mobilewash_unique_active_plate_company",
            )
        ]
        indexes = [
            models.Index(fields=["company", "is_active"]),
            models.Index(fields=["license_plate"]),
        ]

    def clean(self):
        if self.license_plate:
            self.license_plate = self.license_plate.strip().upper()

    def save(self, *args, **kwargs):
        if self.license_plate:
            self.license_plate = self.license_plate.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.license_plate or self.internal_fleet_number or f"Vehicule {self.pk}"


class RecurringSchedule(TimestampedModel):
    WEEKDAY_CHOICES = [
        (0, "Lundi"),
        (1, "Mardi"),
        (2, "Mercredi"),
        (3, "Jeudi"),
        (4, "Vendredi"),
        (5, "Samedi"),
        (6, "Dimanche"),
    ]

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="schedules")
    company = models.ForeignKey(CorporateCompany, on_delete=models.PROTECT, related_name="schedules")
    service_location = models.TextField()
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES)
    planned_start_time = models.TimeField()
    planned_duration_minutes = models.PositiveIntegerField(default=120)
    planned_vehicles = models.PositiveIntegerField(default=12)
    default_assigned_team = models.ManyToManyField(User, blank=True, related_name="mobile_default_schedules")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    instructions = models.TextField(blank=True)

    class Meta:
        verbose_name = "Programme recurrent mobile"
        verbose_name_plural = "Programmes recurrents mobiles"
        ordering = ["weekday", "planned_start_time"]
        indexes = [
            models.Index(fields=["company", "is_active"]),
            models.Index(fields=["contract", "is_active"]),
            models.Index(fields=["weekday", "is_active"]),
        ]

    def clean(self):
        if self.company_id and self.contract_id and self.contract.company_id != self.company_id:
            raise ValidationError({"company": "L'entreprise doit correspondre au contrat."})
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "La fin ne peut pas preceder le debut."})

    def generate_work_orders(self, date_from, date_to, created_by=None):
        if date_to < date_from:
            return []
        cursor = max(date_from, self.start_date)
        end = min(date_to, self.end_date) if self.end_date else date_to
        generated = []
        while cursor <= end:
            if cursor.weekday() == self.weekday and self.is_active:
                scheduled_start = timezone.make_aware(
                    timezone.datetime.combine(cursor, self.planned_start_time),
                    timezone.get_current_timezone(),
                )
                with transaction.atomic():
                    work_order, created = WorkOrder.objects.get_or_create(
                        schedule=self,
                        scheduled_start=scheduled_start,
                        defaults={
                            "contract": self.contract,
                            "company": self.company,
                            "service_location": self.service_location,
                            "planned_duration_minutes": self.planned_duration_minutes,
                            "planned_vehicles": self.planned_vehicles,
                            "team_leader": self.default_assigned_team.first(),
                            "created_by": created_by,
                        },
                    )
                    if created:
                        work_order.assigned_employees.set(self.default_assigned_team.all())
                        work_order.create_number()
                        generated.append(work_order)
            cursor += timedelta(days=1)
        return generated

    def __str__(self):
        return f"{self.company} - {self.get_weekday_display()} {self.planned_start_time}"


class WorkOrder(TimestampedModel):
    STATUS_SCHEDULED = "SCHEDULED"
    STATUS_DISPATCHED = "DISPATCHED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    STATUS_SUBMITTED = "SUBMITTED"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_NO_ACCESS = "NO_ACCESS"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Planifie"),
        (STATUS_DISPATCHED, "Equipe envoyee"),
        (STATUS_IN_PROGRESS, "En cours"),
        (STATUS_AWAITING_CONFIRMATION, "Attente confirmation client"),
        (STATUS_SUBMITTED, "Soumis pour revue"),
        (STATUS_COMPLETED, "Termine"),
        (STATUS_CANCELLED, "Annule"),
        (STATUS_NO_ACCESS, "Acces impossible"),
    ]
    PRICE_CHOICES = [
        ("INCLUDED", "Inclus contrat"),
        ("ADDITIONAL", "Supplementaire"),
        ("SPECIAL", "Service special"),
    ]

    work_order_number = models.CharField(max_length=40, unique=True, blank=True)
    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="work_orders")
    company = models.ForeignKey(CorporateCompany, on_delete=models.PROTECT, related_name="work_orders")
    schedule = models.ForeignKey(RecurringSchedule, on_delete=models.SET_NULL, null=True, blank=True, related_name="work_orders")
    service_location = models.TextField()
    scheduled_start = models.DateTimeField(db_index=True)
    planned_duration_minutes = models.PositiveIntegerField(default=120)
    actual_arrival = models.DateTimeField(null=True, blank=True)
    actual_departure = models.DateTimeField(null=True, blank=True)
    assigned_employees = models.ManyToManyField(User, blank=True, related_name="mobile_work_orders")
    team_leader = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="mobile_work_orders_led")
    planned_vehicles = models.PositiveIntegerField(default=0)
    price_classification = models.CharField(max_length=20, choices=PRICE_CHOICES, default="INCLUDED")
    client_representative_name = models.CharField(max_length=160, blank=True)
    client_signature = models.ImageField(upload_to=signature_upload_path, validators=[validate_mobile_image], null=True, blank=True)
    client_confirmed_at = models.DateTimeField(null=True, blank=True)
    associate_name = models.CharField(max_length=160, blank=True)
    associate_signature = models.ImageField(upload_to=signature_upload_path, validators=[validate_mobile_image], null=True, blank=True)
    associate_confirmed_at = models.DateTimeField(null=True, blank=True)
    observations = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)
    no_access_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="mobile_work_orders_reviewed")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="mobile_work_orders_created")

    class Meta:
        verbose_name = "Ordre de travail mobile"
        verbose_name_plural = "Ordres de travail mobiles"
        ordering = ["-scheduled_start", "work_order_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "scheduled_start"],
                condition=Q(schedule__isnull=False),
                name="mobilewash_one_workorder_per_schedule_visit",
            )
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["contract", "status"]),
            models.Index(fields=["scheduled_start", "status"]),
            models.Index(fields=["status", "reviewed_at"]),
        ]

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_SCHEDULED, db_index=True)

    def __str__(self):
        return self.work_order_number or f"OT mobile {self.pk}"

    @property
    def vehicles_completed_count(self):
        return self.vehicle_lines.filter(status=WorkOrderVehicle.STATUS_COMPLETED).count()

    @property
    def revenue_amount(self):
        line_total = self.vehicle_lines.aggregate(total=models.Sum("billable_amount"))["total"] or Decimal("0.00")
        if line_total:
            return line_total
        completed = self.vehicles_completed_count
        return Decimal(completed) * STANDARD_PRICE

    @property
    def direct_cost_amount(self):
        fields = [
            "machine_fuel_amount",
            "soap_cost",
            "perfume_cost",
            "water_cost",
            "other_consumables_cost",
            "transportation_cost",
            "equipment_maintenance_allocation",
        ]
        return sum((getattr(self, field) or Decimal("0.00")) for field in fields)

    @property
    def contribution_margin(self):
        return self.revenue_amount - self.direct_cost_amount

    machine_fuel_litres = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)])
    machine_fuel_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)])
    soap_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)])
    perfume_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)])
    water_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)])
    other_consumables_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)])
    transportation_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)])
    equipment_maintenance_allocation = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default=USD)

    def clean(self):
        if self.company_id and self.contract_id and self.contract.company_id != self.company_id:
            raise ValidationError({"company": "L'entreprise doit correspondre au contrat."})
        if self.status == self.STATUS_COMPLETED:
            self.validate_completion()

    def create_number(self):
        if self.work_order_number:
            return self.work_order_number
        if not self.pk:
            self.save()
        self.work_order_number = f"OTM-{timezone.localdate():%Y%m}-{self.pk:05d}"
        self.save(update_fields=["work_order_number", "updated_at"])
        return self.work_order_number

    def validate_completion(self, override_review=False):
        errors = {}
        if self.vehicles_completed_count < 1:
            errors["vehicle_lines"] = "Au moins un vehicule doit etre marque termine."
        if not self.associate_name:
            errors["associate_name"] = "Le nom de l'associe Shine Congo est obligatoire."
        if not self.client_representative_name:
            errors["client_representative_name"] = "Le representant client est obligatoire."
        if not self.associate_signature:
            errors["associate_signature"] = "La signature de l'associe est obligatoire."
        if not self.client_signature:
            errors["client_signature"] = "La signature client est obligatoire."
        if not override_review and not self.reviewed_at:
            errors["reviewed_at"] = "La revue manager est obligatoire avant cloture."
        if errors:
            raise ValidationError(errors)

    def submit_for_review(self, user):
        self.status = self.STATUS_SUBMITTED
        now = timezone.now()
        if self.associate_name and not self.associate_confirmed_at:
            self.associate_confirmed_at = now
        if self.client_representative_name and not self.client_confirmed_at:
            self.client_confirmed_at = now
        self.save()
        AuditLog.log(user, "CHANGER_STATUT", "Ordre mobile soumis pour revue", content_object=self)

    def approve_completion(self, user, override_review=False):
        self.validate_completion(override_review=override_review)
        now = timezone.now()
        self.status = self.STATUS_COMPLETED
        self.reviewed_by = self.reviewed_by or user
        self.reviewed_at = self.reviewed_at or now
        self.completed_at = self.completed_at or now
        self.save()
        AuditLog.log(user, "CHANGER_STATUT", "Ordre mobile termine", content_object=self)

    def can_field_user_edit(self, user):
        if self.status in {self.STATUS_COMPLETED, self.STATUS_CANCELLED} or self.reviewed_at:
            return False
        return self.assigned_employees.filter(pk=user.pk).exists()


class WorkOrderVehicle(TimestampedModel):
    STATUS_PENDING = "PENDING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_SKIPPED = "SKIPPED"
    STATUS_REWASH = "REWASH"
    STATUS_CHOICES = [
        (STATUS_PENDING, "A faire"),
        (STATUS_COMPLETED, "Termine"),
        (STATUS_SKIPPED, "Non lave"),
        (STATUS_REWASH, "Relavage"),
    ]

    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="vehicle_lines")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, null=True, blank=True, related_name="work_order_lines")
    license_plate_snapshot = models.CharField(max_length=60, blank=True)
    service_type = models.CharField(max_length=80, default="STANDARD")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    billable_amount = models.DecimalField(max_digits=10, decimal_places=2, default=STANDARD_PRICE, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default=USD)
    before_photo = models.ImageField(upload_to=proof_upload_path, validators=[validate_mobile_image], null=True, blank=True)
    after_photo = models.ImageField(upload_to=proof_upload_path, validators=[validate_mobile_image], null=True, blank=True)
    observations = models.TextField(blank=True)

    class Meta:
        verbose_name = "Vehicule lave sur ordre"
        verbose_name_plural = "Vehicules laves sur ordre"
        ordering = ["work_order", "license_plate_snapshot", "id"]
        indexes = [
            models.Index(fields=["work_order", "status"]),
            models.Index(fields=["vehicle", "status"]),
        ]

    def save(self, *args, **kwargs):
        if self.vehicle and not self.license_plate_snapshot:
            self.license_plate_snapshot = self.vehicle.license_plate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.license_plate_snapshot or str(self.vehicle) or f"Ligne {self.pk}"


class WorkOrderProofPhoto(TimestampedModel):
    PHOTO_TYPE_CHOICES = [
        ("BEFORE", "Avant"),
        ("AFTER", "Apres"),
        ("SIGNATURE", "Signature"),
        ("OTHER", "Autre"),
    ]

    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="proof_photos")
    photo = models.ImageField(upload_to=proof_upload_path, validators=[validate_mobile_image])
    photo_type = models.CharField(max_length=20, choices=PHOTO_TYPE_CHOICES, default="OTHER")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Preuve photo mobile"
        verbose_name_plural = "Preuves photo mobiles"
        ordering = ["-created_at"]
