from django.db import models
import uuid
from decimal import Decimal
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.utils import timezone
import os

from comptes.image_utils import ensure_image_thumbnail, get_thumbnail_url, optimize_image_upload


def current_month_start():
    today = timezone.localdate()
    return today.replace(day=1)


DEFAULT_WATER_SUPPLIER_NAME = "Honosha's Forage"
DEFAULT_WATER_SUPPLIER_RATE_FC = Decimal("22000")


class Location(models.Model):
    """
    Site/Location de lavage (ex: Station Texaco Gombe, Station Total Lemba, etc.)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=200, verbose_name="Nom du site")
    adresse = models.TextField(blank=True, verbose_name="Adresse")
    ville = models.CharField(max_length=100, default="Kinshasa", verbose_name="Ville")
    telephone = models.CharField(max_length=20, blank=True, verbose_name="Téléphone")
    actif = models.BooleanField(default=True, verbose_name="Actif")
    
    # QR Code fixe par site
    site_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, verbose_name="Token du site")
    
    # GPS optionnel (anti-fraude)
    latitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Latitude"
    )
    longitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Longitude"
    )
    rayon_autorisé_mètres = models.IntegerField(
        default=50,
        verbose_name="Rayon autorisé (mètres)",
        help_text="Rayon autour du site pour la vérification GPS"
    )
    gps_actif = models.BooleanField(
        default=False,
        verbose_name="GPS actif",
        help_text="Activer la vérification GPS pour ce site"
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Site"
        verbose_name_plural = "Sites"
        ordering = ["nom"]
    
    def __str__(self):
        return self.nom
    
    def get_qr_url(self):
        """
        Retourne l'URL du QR code fixe pour ce site
        """
        from django.urls import reverse
        return reverse('scan_qr_fixe', kwargs={'site_token': str(self.site_token)})
    
    def calculate_distance(self, lat, lon):
        """
        Calcule la distance en mètres entre le site et une position GPS donnée
        Utilise la formule de Haversine
        """
        if not self.latitude or not self.longitude:
            return None
        
        from math import radians, cos, sin, asin, sqrt
        
        # Convertir en radians
        lat1 = radians(float(self.latitude))
        lon1 = radians(float(self.longitude))
        lat2 = radians(float(lat))
        lon2 = radians(float(lon))
        
        # Formule de Haversine
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        
        # Rayon de la Terre en mètres
        r = 6371000
        
        return c * r


class WaterSupplier(models.Model):
    """
    Fournisseur/contracteur utilisé pour les remplissages d'eau.
    """

    name = models.CharField(max_length=200, unique=True, verbose_name="Nom")
    price_per_tank_fc = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=DEFAULT_WATER_SUPPLIER_RATE_FC,
        validators=[MinValueValidator(0)],
        verbose_name="Prix par remplissage (FC)",
    )
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    is_default = models.BooleanField(default=False, verbose_name="Fournisseur par défaut")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Fournisseur d'eau"
        verbose_name_plural = "Fournisseurs d'eau"
        ordering = ["-is_default", "name"]

    def save(self, *args, **kwargs):
        if self.is_default and not self.is_active:
            self.is_active = True

        super().save(*args, **kwargs)

        if self.is_default:
            WaterSupplier.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
            return

        if WaterSupplier.objects.exclude(pk=self.pk).filter(is_default=True).exists():
            return

        replacement = (
            WaterSupplier.objects.exclude(pk=self.pk)
            .filter(is_active=True)
            .order_by("name")
            .first()
        )
        if replacement:
            WaterSupplier.objects.filter(pk=replacement.pk).update(is_default=True)
            return

        WaterSupplier.objects.filter(pk=self.pk).update(is_default=True, is_active=True)
        self.is_default = True
        self.is_active = True

    def __str__(self):
        return self.name


def get_default_water_supplier():
    supplier = WaterSupplier.objects.filter(is_default=True).order_by("name").first()
    if supplier:
        if not supplier.is_active:
            supplier.is_active = True
            supplier.save(update_fields=["is_active", "updated_at"])
        return supplier

    supplier = WaterSupplier.objects.filter(is_active=True).order_by("name").first()
    if supplier:
        supplier.is_default = True
        supplier.save(update_fields=["is_default", "updated_at"])
        return supplier

    supplier, created = WaterSupplier.objects.get_or_create(
        name=DEFAULT_WATER_SUPPLIER_NAME,
        defaults={
            "price_per_tank_fc": DEFAULT_WATER_SUPPLIER_RATE_FC,
            "is_active": True,
            "is_default": True,
        },
    )
    supplier_changed = created is False and (
        supplier.price_per_tank_fc != DEFAULT_WATER_SUPPLIER_RATE_FC
        or not supplier.is_active
        or not supplier.is_default
    )
    if supplier_changed:
        supplier.price_per_tank_fc = DEFAULT_WATER_SUPPLIER_RATE_FC
        supplier.is_active = True
        supplier.is_default = True
        supplier.save(update_fields=["price_per_tank_fc", "is_active", "is_default", "updated_at"])
    return supplier


def get_default_water_supplier_pk():
    return get_default_water_supplier().pk


class DailyBankDeposit(models.Model):
    """
    Dépôt bancaire quotidien par site
    Enregistre le montant déposé à la banque à la fin de chaque journée
    """
    site = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="bank_deposits", verbose_name="Site")
    date = models.DateField(verbose_name="Date du dépôt")
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Montant déposé (FC)"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_deposits_created",
        verbose_name="Enregistré par"
    )
    is_system_generated = models.BooleanField(
        default=False,
        verbose_name="Généré automatiquement",
    )
    system_source = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Source système",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Dépôt Bancaire Quotidien"
        verbose_name_plural = "Dépôts Bancaires Quotidiens"
        unique_together = [["site", "date"]]
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["site", "date"]),
            models.Index(fields=["is_system_generated", "system_source"]),
            models.Index(fields=["-date"]),
        ]
    
    def __str__(self):
        return f"{self.site.nom} - {self.date} - {self.amount} FC"


class SiteLossEntry(models.Model):
    """
    Enregistrement des pertes/dépenses d'un site par date.
    Permet de suivre les pertes financées par la caisse ou par la banque.
    """

    CATEGORY_CHOICES = [
        ("TRANSPORT", "Transport"),
        ("PANNE", "Panne / Réparation"),
        ("CONSOMMABLE", "Consommables"),
        ("URGENCE", "Urgence / Incident"),
        ("RETRAIT_BANQUE", "Retrait banque"),
        ("AUTRE", "Autre perte"),
    ]

    FUNDING_SOURCE_CHOICES = [
        ("CAISSE", "Caisse du jour"),
        ("BANQUE", "Banque"),
    ]

    site = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="loss_entries",
        verbose_name="Site",
    )
    date = models.DateField(verbose_name="Date")
    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default="AUTRE",
        verbose_name="Type de perte",
    )
    funding_source = models.CharField(
        max_length=10,
        choices=FUNDING_SOURCE_CHOICES,
        default="CAISSE",
        verbose_name="Source des fonds",
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Montant (FC)",
    )
    title = models.CharField(max_length=200, verbose_name="Titre")
    description = models.TextField(blank=True, verbose_name="Description")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="site_losses_created",
        verbose_name="Enregistré par",
    )
    is_system_generated = models.BooleanField(
        default=False,
        verbose_name="Généré automatiquement",
    )
    system_source = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Source système",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Perte du Site"
        verbose_name_plural = "Pertes du Site"
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["site", "date"]),
            models.Index(fields=["is_system_generated", "system_source"]),
            models.Index(fields=["site", "category"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.site.nom} - {self.date} - {self.title} ({self.amount} FC)"


class SiteJournalEntry(models.Model):
    """
    Journal libre du site pour les suivis opérationnels de l'admin.
    Peut contenir une information simple ou une action avec montant optionnel.
    """

    CATEGORY_CHOICES = [
        ("INFO", "Information"),
        ("SUIVI", "Suivi"),
        ("INTERVENTION", "Intervention"),
        ("DEPENSE", "Dépense / avance"),
        ("INCIDENT", "Incident"),
        ("AUTRE", "Autre"),
    ]

    site = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="journal_entries",
        verbose_name="Site",
    )
    entry_date = models.DateField(verbose_name="Date")
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default="INFO",
        verbose_name="Catégorie",
    )
    title = models.CharField(max_length=200, verbose_name="Titre")
    description = models.TextField(blank=True, verbose_name="Détails")
    amount_fc = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        null=True,
        blank=True,
        verbose_name="Montant lié (FC)",
    )
    reminder_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Rappel email prévu pour",
        help_text="Optionnel. Le système enverra un email de rappel à la date et l'heure choisies.",
    )
    reminder_email = models.EmailField(
        blank=True,
        verbose_name="Email de rappel",
        help_text="Défini automatiquement à partir de l'email de l'administrateur connecté.",
    )
    reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Rappel envoyé le",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="site_journal_entries_created",
        verbose_name="Enregistré par",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Journal du Site"
        verbose_name_plural = "Journal du Site"
        ordering = ["-entry_date", "-created_at"]
        indexes = [
            models.Index(fields=["site", "entry_date"]),
            models.Index(fields=["site", "category"]),
            models.Index(fields=["reminder_at"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.site.nom} - {self.entry_date} - {self.title}"


class SiteWaterPurchase(models.Model):
    """
    Suivi des achats d'eau effectués pour un site.
    Sert à comptabiliser les remplissages payés au cours du mois.
    """

    site = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="water_purchases",
        verbose_name="Site",
    )
    supplier = models.ForeignKey(
        WaterSupplier,
        on_delete=models.PROTECT,
        related_name="water_purchases",
        default=get_default_water_supplier_pk,
        verbose_name="Fournisseur / forage",
    )
    billing_month = models.DateField(
        default=current_month_start,
        verbose_name="Mois concerné",
        help_text="Le mois à facturer au propriétaire du forage.",
    )
    purchase_date = models.DateField(verbose_name="Date d'achat")
    reporting_week_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Semaine imputee",
        help_text="Optionnel: choisissez un jour de la semaine du mois concerne pour y rattacher cet achat.",
    )
    amount_fc = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=DEFAULT_WATER_SUPPLIER_RATE_FC,
        validators=[MinValueValidator(0)],
        verbose_name="Montant (FC)",
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="site_water_purchases_created",
        verbose_name="Enregistré par",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Achat d'eau du Site"
        verbose_name_plural = "Achats d'eau du Site"
        ordering = ["-billing_month", "-purchase_date", "-created_at"]
        indexes = [
            models.Index(fields=["site", "billing_month"]),
            models.Index(fields=["site", "purchase_date"]),
            models.Index(fields=["-created_at"]),
        ]

    def _date_is_in_billing_month(self, value):
        return bool(
            value
            and self.billing_month
            and value.year == self.billing_month.year
            and value.month == self.billing_month.month
        )

    def get_reporting_week_date(self):
        if self._date_is_in_billing_month(self.reporting_week_date):
            return self.reporting_week_date
        if self._date_is_in_billing_month(self.purchase_date):
            return self.purchase_date
        return None

    def save(self, *args, **kwargs):
        if self.billing_month:
            self.billing_month = self.billing_month.replace(day=1)
        if self.reporting_week_date and not self._date_is_in_billing_month(self.reporting_week_date):
            self.reporting_week_date = None
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.site.nom} - {self.supplier.name} - "
            f"{self.billing_month:%m/%Y} - {self.purchase_date} - {self.amount_fc} FC"
        )


def site_document_path(instance, filename):
    """Chemin de sauvegarde des documents du site"""
    site_id = str(instance.site.id)
    file_type = instance.file_type.lower()
    return f"sites/{site_id}/{file_type}/{filename}"


def camera_evidence_path(instance, filename):
    """Chemin de sauvegarde des preuves vidéo/capture liées aux caméras."""
    site_id = str(instance.daily_report.site_id)
    report_date = instance.daily_report.date.strftime("%Y-%m-%d")
    ext = os.path.splitext(filename)[1].lower()
    safe_ext = ext or ".bin"
    camera_segment = f"camera-{instance.camera_id or 'unknown'}"
    title_slug = (instance.title or "evidence").strip().replace(" ", "-").lower()
    title_slug = "".join(char for char in title_slug if char.isalnum() or char in {"-", "_"})
    title_slug = title_slug[:60] or "evidence"
    return f"sites/{site_id}/camera-evidence/{report_date}/{camera_segment}/{title_slug}{safe_ext}"


def camera_observation_evidence_path(instance, filename):
    """Chemin de sauvegarde des captures fournies par les contrôleurs caméra."""
    report = instance.observation.report
    site_id = str(report.site_id)
    report_date = report.date.strftime("%Y-%m-%d")
    ext = os.path.splitext(filename)[1].lower()
    safe_ext = ext or ".jpg"
    observation_segment = f"observation-{instance.observation_id or 'new'}"
    evidence_segment = instance.evidence_kind.lower()
    return (
        f"sites/{site_id}/camera-operator-evidence/{report_date}/"
        f"{observation_segment}/{evidence_segment}{safe_ext}"
    )


class SiteDocument(models.Model):
    """
    Documents et fichiers liés à un site
    Contrats, paiements, photos de construction, vidéos, etc.
    """
    FILE_TYPE_CHOICES = [
        ("CONTRAT", "Contrat avec le prêteur"),
        ("PAIEMENT", "Paiement de location"),
        ("COMPTE_BANCAIRE", "Photo compte bancaire du prêteur"),
        ("PHOTO_CONSTRUCTION", "Photo de construction"),
        ("VIDEO_CONSTRUCTION", "Vidéo de construction"),
        ("AUTRE_DOCUMENT", "Autre document"),
        ("AUTRE_PHOTO", "Autre photo"),
        ("AUTRE_VIDEO", "Autre vidéo"),
    ]
    
    site = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="documents", verbose_name="Site")
    file_type = models.CharField(
        max_length=30,
        choices=FILE_TYPE_CHOICES,
        default="AUTRE_DOCUMENT",
        verbose_name="Type de fichier"
    )
    title = models.CharField(max_length=200, verbose_name="Titre")
    description = models.TextField(blank=True, verbose_name="Description")
    file = models.FileField(upload_to=site_document_path, verbose_name="Fichier")
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="site_documents_uploaded",
        verbose_name="Uploadé par"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="Uploadé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Document du Site"
        verbose_name_plural = "Documents du Site"
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["site", "file_type"]),
            models.Index(fields=["-uploaded_at"]),
        ]
    
    def __str__(self):
        return f"{self.site.nom} - {self.get_file_type_display()} - {self.title}"
    
    def filename(self):
        """Retourne le nom du fichier"""
        return os.path.basename(self.file.name)
    
    def is_image(self):
        """Vérifie si le fichier est une image"""
        ext = os.path.splitext(self.file.name)[1].lower()
        return ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
    
    def is_video(self):
        """Vérifie si le fichier est une vidéo"""
        ext = os.path.splitext(self.file.name)[1].lower()
        return ext in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv']
    
    def is_pdf(self):
        """Vérifie si le fichier est un PDF"""
        return os.path.splitext(self.file.name)[1].lower() == '.pdf'
    
    def file_size_mb(self):
        """Retourne la taille du fichier en MB"""
        try:
            size = self.file.size
            return round(size / (1024 * 1024), 2)
        except:
            return 0


class Camera(models.Model):
    CAMERA_POSITION_CHOICES = [
        ("GATE", "Entrée / gate"),
        ("WORK_AREA", "Zone de travail"),
        ("TOOLS_AREA", "Zone outils"),
        ("PAYMENT_AREA", "Zone paiement"),
        ("OUTSIDE", "Extérieur"),
    ]

    name = models.CharField(max_length=150, verbose_name="Nom de la caméra")
    site = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="cameras",
        verbose_name="Site",
    )
    camera_number = models.PositiveIntegerField(verbose_name="Numéro de caméra")
    camera_position = models.CharField(
        max_length=20,
        choices=CAMERA_POSITION_CHOICES,
        default="GATE",
        verbose_name="Position",
    )
    app_name = models.CharField(max_length=120, blank=True, verbose_name="Nom de l'application")
    notes = models.TextField(blank=True, verbose_name="Notes")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créée le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifiée le")

    class Meta:
        verbose_name = "Caméra"
        verbose_name_plural = "Caméras"
        ordering = ["site__nom", "camera_number", "name"]
        unique_together = [["site", "camera_number"]]
        indexes = [
            models.Index(fields=["site", "is_active"]),
            models.Index(fields=["site", "camera_position"]),
        ]

    def __str__(self):
        return f"{self.site.nom} - Caméra {self.camera_number} - {self.name}"


class DailyCameraReport(models.Model):
    CAR_PRICE_FC = Decimal("15000")
    MOTO_PRICE_FC = Decimal("3000")
    THREE_WHEELER_PRICE_FC = Decimal("5000")

    site = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="daily_camera_reports",
        verbose_name="Site",
    )
    date = models.DateField(verbose_name="Date")
    cars_count = models.PositiveIntegerField(default=0, verbose_name="Nombre de voitures")
    motos_count = models.PositiveIntegerField(default=0, verbose_name="Nombre de motos (2 pneus)")
    three_wheelers_count = models.PositiveIntegerField(default=0, verbose_name="Nombre de motos à 3 pneus")
    total_vehicles = models.PositiveIntegerField(default=0, verbose_name="Total véhicules")
    expected_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="Recette attendue (FC)",
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_camera_reports_created",
        verbose_name="Créé par",
    )
    ai_cars_count = models.PositiveIntegerField(null=True, blank=True, verbose_name="AI voitures")
    ai_motos_count = models.PositiveIntegerField(null=True, blank=True, verbose_name="AI motos")
    ai_confidence_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Score confiance AI",
    )
    final_cars_count = models.PositiveIntegerField(null=True, blank=True, verbose_name="Voitures finales")
    final_motos_count = models.PositiveIntegerField(null=True, blank=True, verbose_name="Motos finales (2 pneus)")
    final_three_wheelers_count = models.PositiveIntegerField(null=True, blank=True, verbose_name="Motos finales à 3 pneus")
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_camera_reports_reviewed",
        verbose_name="Revu par",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="Revu le")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Rapport caméra quotidien"
        verbose_name_plural = "Rapports caméra quotidiens"
        ordering = ["-date", "-created_at"]
        unique_together = [["site", "date"]]
        indexes = [
            models.Index(fields=["site", "date"]),
            models.Index(fields=["-date"]),
        ]

    def __str__(self):
        return f"{self.site.nom} - {self.date:%d/%m/%Y}"

    @property
    def manual_total_vehicles(self):
        return (self.cars_count or 0) + (self.motos_count or 0) + (self.three_wheelers_count or 0)

    @property
    def manual_expected_revenue(self):
        return (
            (Decimal(self.cars_count or 0) * self.CAR_PRICE_FC)
            + (Decimal(self.motos_count or 0) * self.MOTO_PRICE_FC)
            + (Decimal(self.three_wheelers_count or 0) * self.THREE_WHEELER_PRICE_FC)
        )

    def sync_computed_fields(self):
        if self.reviewed_by_id is None:
            self.final_cars_count = self.cars_count or 0
            self.final_motos_count = self.motos_count or 0
            self.final_three_wheelers_count = self.three_wheelers_count or 0
        else:
            if self.final_cars_count is None:
                self.final_cars_count = self.cars_count or 0
            if self.final_motos_count is None:
                self.final_motos_count = self.motos_count or 0
            if self.final_three_wheelers_count is None:
                self.final_three_wheelers_count = self.three_wheelers_count or 0

        effective_cars = self.final_cars_count if self.final_cars_count is not None else (self.cars_count or 0)
        effective_motos = self.final_motos_count if self.final_motos_count is not None else (self.motos_count or 0)
        effective_three_wheelers = (
            self.final_three_wheelers_count
            if self.final_three_wheelers_count is not None
            else (self.three_wheelers_count or 0)
        )
        self.total_vehicles = int(effective_cars + effective_motos + effective_three_wheelers)
        self.expected_revenue = (
            Decimal(effective_cars) * self.CAR_PRICE_FC
            + Decimal(effective_motos) * self.MOTO_PRICE_FC
            + Decimal(effective_three_wheelers) * self.THREE_WHEELER_PRICE_FC
        )

    def save(self, *args, **kwargs):
        self.sync_computed_fields()
        super().save(*args, **kwargs)


class VideoEvidence(models.Model):
    EVIDENCE_TYPE_CHOICES = [
        ("CAR_COUNT", "Comptage voitures"),
        ("EMPLOYEE_WORK", "Travail employé"),
        ("THEFT_SECURITY", "Sécurité / vol"),
        ("WATER_TANK", "Réservoir d'eau"),
        ("GENERATOR_FUEL", "Carburant groupe"),
        ("OTHER", "Autre"),
    ]

    daily_report = models.ForeignKey(
        DailyCameraReport,
        on_delete=models.CASCADE,
        related_name="video_evidences",
        verbose_name="Rapport quotidien",
    )
    camera = models.ForeignKey(
        Camera,
        on_delete=models.CASCADE,
        related_name="video_evidences",
        verbose_name="Caméra",
    )
    title = models.CharField(max_length=200, verbose_name="Titre")
    evidence_type = models.CharField(
        max_length=20,
        choices=EVIDENCE_TYPE_CHOICES,
        default="OTHER",
        verbose_name="Type de preuve",
    )
    clip_date = models.DateField(verbose_name="Date du clip")
    start_time = models.TimeField(null=True, blank=True, verbose_name="Heure début")
    end_time = models.TimeField(null=True, blank=True, verbose_name="Heure fin")
    uploaded_file = models.FileField(upload_to=camera_evidence_path, verbose_name="Clip ou capture")
    s3_url = models.URLField(blank=True, verbose_name="URL S3")
    notes = models.TextField(blank=True, verbose_name="Notes")
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="video_evidences_uploaded",
        verbose_name="Uploadé par",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")

    class Meta:
        verbose_name = "Preuve vidéo"
        verbose_name_plural = "Preuves vidéo"
        ordering = ["-clip_date", "-created_at"]
        indexes = [
            models.Index(fields=["daily_report", "clip_date"]),
            models.Index(fields=["camera", "evidence_type"]),
        ]

    def __str__(self):
        return f"{self.daily_report.site.nom} - {self.title}"

    def filename(self):
        return os.path.basename(self.uploaded_file.name) if self.uploaded_file else ""

    def is_image(self):
        ext = os.path.splitext(self.filename())[1].lower()
        return ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]

    def is_video(self):
        ext = os.path.splitext(self.filename())[1].lower()
        return ext in [".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mkv", ".m4v"]

    @property
    def image_thumbnail_url(self):
        if not self.is_image():
            return getattr(self.uploaded_file, "url", "")
        return get_thumbnail_url(self.uploaded_file)

    def save(self, *args, **kwargs):
        if self.uploaded_file and not self.uploaded_file._committed and self.is_image():
            self.uploaded_file = optimize_image_upload(self.uploaded_file)
        super().save(*args, **kwargs)
        if self.uploaded_file:
            resolved_url = getattr(self.uploaded_file, "url", "") or ""
            if resolved_url and self.s3_url != resolved_url:
                type(self).objects.filter(pk=self.pk).update(s3_url=resolved_url)
                self.s3_url = resolved_url
            if self.is_image():
                ensure_image_thumbnail(self.uploaded_file)


class CameraOperatorDailyReport(models.Model):
    CAR_PRICE_FC = DailyCameraReport.CAR_PRICE_FC
    MOTO_PRICE_FC = DailyCameraReport.MOTO_PRICE_FC
    THREE_WHEELER_PRICE_FC = DailyCameraReport.THREE_WHEELER_PRICE_FC

    site = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="camera_operator_reports",
        verbose_name="Site",
    )
    controller = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="camera_operator_reports",
        verbose_name="Contrôleur caméra",
    )
    date = models.DateField(verbose_name="Date")
    cars_count = models.PositiveIntegerField(default=0, verbose_name="Voitures")
    motos_count = models.PositiveIntegerField(default=0, verbose_name="Motos 2 roues")
    three_wheelers_count = models.PositiveIntegerField(default=0, verbose_name="Motos 3 roues")
    total_vehicles = models.PositiveIntegerField(default=0, verbose_name="Total véhicules")
    screenshots_count = models.PositiveIntegerField(default=0, verbose_name="Captures véhicule")
    time_proof_count = models.PositiveIntegerField(default=0, verbose_name="Preuves horaires")
    expected_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="Recette attendue (FC)",
    )
    notes = models.TextField(blank=True, verbose_name="Notes de fin de journée")
    is_submitted = models.BooleanField(default=False, verbose_name="Rapport final soumis")
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name="Soumis le")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Rapport contrôleur caméra"
        verbose_name_plural = "Rapports contrôleurs caméra"
        ordering = ["-date", "-updated_at"]
        unique_together = [["site", "controller", "date"]]
        indexes = [
            models.Index(fields=["site", "date"]),
            models.Index(fields=["controller", "date"]),
            models.Index(fields=["site", "is_submitted"]),
        ]

    def __str__(self):
        controller_name = self.controller.get_full_name() or self.controller.username
        return f"{self.site.nom} - {controller_name} - {self.date:%d/%m/%Y}"

    def sync_observation_totals(self, save=True):
        observations = list(self.observations.all())
        cars_count = sum(1 for item in observations if item.vehicle_type == CameraObservation.VEHICLE_CAR)
        motos_count = sum(1 for item in observations if item.vehicle_type == CameraObservation.VEHICLE_MOTO)
        three_wheelers_count = sum(
            1 for item in observations if item.vehicle_type == CameraObservation.VEHICLE_THREE_WHEELER
        )
        screenshot_total = sum(item.screenshot_count for item in observations)
        time_proof_total = sum(item.time_proof_count for item in observations)

        self.cars_count = cars_count
        self.motos_count = motos_count
        self.three_wheelers_count = three_wheelers_count
        self.total_vehicles = cars_count + motos_count + three_wheelers_count
        self.screenshots_count = screenshot_total
        self.time_proof_count = time_proof_total
        self.expected_revenue = (
            Decimal(cars_count) * self.CAR_PRICE_FC
            + Decimal(motos_count) * self.MOTO_PRICE_FC
            + Decimal(three_wheelers_count) * self.THREE_WHEELER_PRICE_FC
        )

        if save and self.pk:
            self.save(
                update_fields=[
                    "cars_count",
                    "motos_count",
                    "three_wheelers_count",
                    "total_vehicles",
                    "screenshots_count",
                    "time_proof_count",
                    "expected_revenue",
                    "updated_at",
                ]
            )


class CameraObservation(models.Model):
    VEHICLE_CAR = "CAR"
    VEHICLE_MOTO = "MOTO"
    VEHICLE_THREE_WHEELER = "THREE_WHEELER"
    VEHICLE_TYPE_CHOICES = [
        (VEHICLE_CAR, "Voiture"),
        (VEHICLE_MOTO, "Moto 2 roues"),
        (VEHICLE_THREE_WHEELER, "Moto 3 roues"),
    ]

    report = models.ForeignKey(
        CameraOperatorDailyReport,
        on_delete=models.CASCADE,
        related_name="observations",
        verbose_name="Rapport contrôleur caméra",
    )
    camera = models.ForeignKey(
        Camera,
        on_delete=models.CASCADE,
        related_name="operator_observations",
        null=True,
        blank=True,
        verbose_name="Caméra",
    )
    vehicle_type = models.CharField(
        max_length=20,
        choices=VEHICLE_TYPE_CHOICES,
        default=VEHICLE_CAR,
        verbose_name="Type de véhicule",
    )
    plate_number = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Plaque",
    )
    observed_time = models.TimeField(null=True, blank=True, verbose_name="Heure observée")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Observation caméra"
        verbose_name_plural = "Observations caméra"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["report", "vehicle_type"]),
            models.Index(fields=["camera", "created_at"]),
        ]

    def __str__(self):
        plate_suffix = f" - {self.plate_number}" if self.plate_number else ""
        return f"{self.report.site.nom} - {self.get_vehicle_type_display()}{plate_suffix} - {self.report.date:%d/%m/%Y}"

    @property
    def screenshot_count(self):
        return self.evidences.filter(evidence_kind=CameraObservationEvidence.KIND_SCREENSHOT).count()

    @property
    def time_proof_count(self):
        return self.evidences.filter(evidence_kind=CameraObservationEvidence.KIND_TIME_PROOF).count()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.report.sync_observation_totals()

    def delete(self, *args, **kwargs):
        report = self.report
        super().delete(*args, **kwargs)
        report.sync_observation_totals()


class CameraObservationEvidence(models.Model):
    KIND_SCREENSHOT = "SCREENSHOT"
    KIND_TIME_PROOF = "TIME_PROOF"
    EVIDENCE_KIND_CHOICES = [
        (KIND_SCREENSHOT, "Capture véhicule"),
        (KIND_TIME_PROOF, "Preuve horaire"),
    ]

    observation = models.ForeignKey(
        CameraObservation,
        on_delete=models.CASCADE,
        related_name="evidences",
        verbose_name="Observation",
    )
    evidence_kind = models.CharField(
        max_length=20,
        choices=EVIDENCE_KIND_CHOICES,
        default=KIND_SCREENSHOT,
        verbose_name="Type de preuve",
    )
    file = models.ImageField(
        upload_to=camera_observation_evidence_path,
        max_length=255,
        verbose_name="Capture",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")

    class Meta:
        verbose_name = "Preuve observation caméra"
        verbose_name_plural = "Preuves observation caméra"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["observation", "evidence_kind"]),
        ]

    def __str__(self):
        return f"{self.observation} - {self.get_evidence_kind_display()}"

    def filename(self):
        return os.path.basename(self.file.name) if self.file else ""

    @property
    def thumbnail_url(self):
        return get_thumbnail_url(self.file)

    def save(self, *args, **kwargs):
        if self.file and not self.file._committed:
            self.file = optimize_image_upload(self.file)
        super().save(*args, **kwargs)
        if self.file:
            ensure_image_thumbnail(self.file)
        self.observation.report.sync_observation_totals()

    def delete(self, *args, **kwargs):
        report = self.observation.report
        super().delete(*args, **kwargs)
        report.sync_observation_totals()
