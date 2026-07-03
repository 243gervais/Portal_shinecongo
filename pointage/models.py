from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal, InvalidOperation
import hashlib
import secrets
import json

from comptes.image_utils import ensure_image_thumbnail, get_thumbnail_url, optimize_image_upload
from pointage.attendance import get_clock_in_status, get_clock_out_status


def attendance_photo_path(instance, filename):
    date_str = (instance.date or timezone.localdate()).strftime("%Y/%m/%d")
    shift_segment = instance.pk or "nouveau"
    employee_segment = instance.employe_id or "employee"
    return f"pointages/{date_str}/{employee_segment}/{shift_segment}/{filename}"


class DailyQRToken(models.Model):
    """
    QR Code du jour par site - Système de sécurité pour les pointages
    """
    site = models.ForeignKey("sites.Location", on_delete=models.CASCADE, verbose_name="Site")
    date = models.DateField(verbose_name="Date")
    nonce = models.CharField(max_length=32, verbose_name="Nonce")
    token = models.CharField(max_length=64, unique=True, verbose_name="Token")
    actif = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    regenerated_at = models.DateTimeField(null=True, blank=True, verbose_name="Régénéré le")
    regenerated_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name="qr_regenerations",
        verbose_name="Régénéré par"
    )
    
    class Meta:
        verbose_name = "QR Token du Jour"
        verbose_name_plural = "QR Tokens du Jour"
        unique_together = [["site", "date", "actif"]]
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["site", "date", "actif"]),
            models.Index(fields=["token"]),
        ]
    
    def __str__(self):
        return f"{self.site.nom} - {self.date} - {'Actif' if self.actif else 'Inactif'}"
    
    @classmethod
    def generate_token(cls, site_id, date_str, nonce):
        """
        Générer un token sécurisé avec HMAC-SHA256
        """
        from django.conf import settings
        secret = settings.QR_SECRET_KEY
        data = f"{site_id}|{date_str}|{nonce}"
        return hashlib.sha256(f"{secret}:{data}".encode()).hexdigest()
    
    @classmethod
    def create_daily_qr(cls, site, date=None, created_by=None):
        """
        Créer un nouveau QR du jour pour un site
        """
        if date is None:
            date = timezone.localdate()
        
        # Désactiver les anciens QR de ce site pour cette date
        cls.objects.filter(site=site, date=date, actif=True).update(actif=False)
        
        # Générer un nouveau token
        nonce = secrets.token_hex(16)
        token = cls.generate_token(str(site.id), str(date), nonce)
        
        qr_token = cls.objects.create(
            site=site,
            date=date,
            nonce=nonce,
            token=token,
            actif=True
        )
        
        return qr_token
    
    def get_qr_payload(self):
        """
        Obtenir le payload JSON pour le QR code
        """
        return json.dumps({
            "v": 1,
            "site_id": str(self.site.id),
            "date": str(self.date),
            "nonce": self.nonce,
            "token": self.token
        })
    
    @classmethod
    def validate_qr_scan(cls, payload_json, employee_site=None):
        """
        Valider un scan de QR code
        Retourne (valid: bool, message: str, qr_token: DailyQRToken or None)
        """
        try:
            payload = json.loads(payload_json)
            site_id = payload.get("site_id")
            date_str = payload.get("date")
            token = payload.get("token")
            
            # Vérifier que la date est aujourd'hui
            today = timezone.localdate()
            if str(today) != date_str:
                return False, "QR invalide ou expiré.", None
            
            # Chercher le token
            try:
                qr_token = cls.objects.get(
                    site__id=site_id,
                    date=date_str,
                    token=token,
                    actif=True
                )
            except cls.DoesNotExist:
                return False, "QR invalide ou expiré.", None
            
            # Vérifier que l'employé est sur le bon site (si employee_site fourni)
            if employee_site and str(qr_token.site.id) != str(employee_site.id):
                return False, "Ce QR appartient à un autre site.", None
            
            return True, "QR valide", qr_token
            
        except (json.JSONDecodeError, KeyError):
            return False, "Format de QR invalide.", None


class ShiftDay(models.Model):
    """
    Pointage d'un employé (entrée et sortie)
    """
    GPS_STATUS_CHOICES = [
        ("OK", "OK"),
        ("HORS_ZONE", "Hors zone"),
        ("INCONNU", "Inconnu"),
    ]
    
    employe = models.ForeignKey(User, on_delete=models.CASCADE, related_name="pointages", verbose_name="Employé")
    site = models.ForeignKey("sites.Location", on_delete=models.CASCADE, verbose_name="Site")
    date = models.DateField(verbose_name="Date")
    
    # Pointage entrée
    clock_in_time = models.DateTimeField(null=True, blank=True, verbose_name="Heure d'entrée")
    clock_in_photo = models.ImageField(
        upload_to=attendance_photo_path,
        blank=True,
        null=True,
        verbose_name="Photo de début de journée",
    )
    clock_in_photo_taken_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Photo entrée prise à",
    )
    
    # Pointage sortie
    clock_out_time = models.DateTimeField(null=True, blank=True, verbose_name="Heure de sortie")
    clock_out_photo = models.ImageField(
        upload_to=attendance_photo_path,
        blank=True,
        null=True,
        verbose_name="Photo de fin de journée",
    )
    clock_out_photo_taken_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Photo sortie prise à",
    )
    
    # GPS pour entrée
    clock_in_gps_latitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Latitude GPS (entrée)"
    )
    clock_in_gps_longitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Longitude GPS (entrée)"
    )
    clock_in_gps_distance_mètres = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        verbose_name="Distance GPS (entrée, mètres)"
    )
    clock_in_gps_status = models.CharField(
        max_length=20,
        choices=GPS_STATUS_CHOICES,
        default="INCONNU",
        verbose_name="Statut GPS (entrée)"
    )
    
    # GPS pour sortie
    clock_out_gps_latitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Latitude GPS (sortie)"
    )
    clock_out_gps_longitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Longitude GPS (sortie)"
    )
    clock_out_gps_distance_mètres = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        verbose_name="Distance GPS (sortie, mètres)"
    )
    clock_out_gps_status = models.CharField(
        max_length=20,
        choices=GPS_STATUS_CHOICES,
        default="INCONNU",
        verbose_name="Statut GPS (sortie)"
    )
    
    # Rapport de fin de journée
    daily_report_confirmed = models.BooleanField(default=False, verbose_name="Rapport confirmé")
    total_lavages_reported = models.IntegerField(default=0, verbose_name="Total lavages déclaré")
    total_amount_reported_fc = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Montant total déclaré (FC)",
    )
    lavages_review = models.TextField(blank=True, verbose_name="Revue des lavages")
    problems_review = models.TextField(blank=True, verbose_name="Revue des problèmes")
    report_notes = models.TextField(blank=True, verbose_name="Notes du rapport")
    daily_expenses = models.JSONField(default=list, blank=True, verbose_name="Depenses du jour")
    daily_expenses_total_fc = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Total depenses du jour (FC)",
    )
    
    # Corrections (manager)
    corrected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pointages_corriges",
        verbose_name="Corrigé par"
    )
    correction_reason = models.TextField(blank=True, verbose_name="Motif de correction")
    corrected_at = models.DateTimeField(null=True, blank=True, verbose_name="Corrigé le")
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Pointage"
        verbose_name_plural = "Pointages"
        unique_together = [["employe", "date"]]
        ordering = ["-date", "-clock_in_time"]
        indexes = [
            models.Index(fields=["employe", "date"]),
            models.Index(fields=["site", "date"]),
            models.Index(fields=["site", "date", "daily_report_confirmed"], name="pointage_site_date_report_idx"),
            models.Index(fields=["employe", "-updated_at"], name="pointage_employe_updated_idx"),
            models.Index(fields=["-created_at"], name="pointage_created_desc_idx"),
        ]
    
    def __str__(self):
        return f"{self.employe.get_full_name() or self.employe.username} - {self.date}"

    @property
    def daily_expense_items(self):
        expense_items = []
        for item in self.daily_expenses or []:
            label = str(item.get("label", "")).strip()
            if not label:
                continue

            try:
                amount_fc = Decimal(str(item.get("amount_fc", "0")))
            except (ArithmeticError, InvalidOperation, TypeError, ValueError):
                amount_fc = Decimal("0")

            if amount_fc < 0:
                amount_fc = Decimal("0")

            expense_items.append({
                "key": str(item.get("key", "")).strip(),
                "label": label,
                "amount_fc": amount_fc,
                "is_known": bool(item.get("is_known")),
            })

        return expense_items

    @property
    def daily_expense_summary(self):
        items = self.daily_expense_items
        if not items:
            return "Aucune depense confirmee."

        return " • ".join(
            f"{item['label']}: {item['amount_fc']:,.0f} FC".replace(",", " ")
            for item in items
        )
    
    def is_complete(self):
        """Vérifie si le pointage est complet (entrée ET sortie)"""
        return self.clock_in_time is not None and self.clock_out_time is not None

    def duration(self):
        """Calcule la durée du shift si complet"""
        if self.is_complete():
            return self.clock_out_time - self.clock_in_time
        return None
    
    def has_missed_punch(self):
        """Vérifie si il manque un pointage de sortie"""
        return self.clock_in_time is not None and self.clock_out_time is None

    @property
    def clock_in_photo_thumbnail_url(self):
        return get_thumbnail_url(self.clock_in_photo)

    @property
    def clock_out_photo_thumbnail_url(self):
        return get_thumbnail_url(self.clock_out_photo)

    def get_clock_in_attendance_status(self, *, reference_time=None):
        return get_clock_in_status(self.date, self.clock_in_time, reference_time=reference_time)

    def get_clock_out_attendance_status(self, *, reference_time=None):
        return get_clock_out_status(self.date, self.clock_out_time, reference_time=reference_time)

    def save(self, *args, **kwargs):
        if self.clock_in_photo and not self.clock_in_photo._committed:
            self.clock_in_photo = optimize_image_upload(self.clock_in_photo)
        if self.clock_out_photo and not self.clock_out_photo._committed:
            self.clock_out_photo = optimize_image_upload(self.clock_out_photo)

        super().save(*args, **kwargs)

        if self.clock_in_photo:
            ensure_image_thumbnail(self.clock_in_photo)
        if self.clock_out_photo:
            ensure_image_thumbnail(self.clock_out_photo)
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal, InvalidOperation
import hashlib
import secrets
import json

from comptes.image_utils import ensure_image_thumbnail, get_thumbnail_url, optimize_image_upload
from pointage.attendance import get_clock_in_status, get_clock_out_status


def attendance_photo_path(instance, filename):
    date_str = (instance.date or timezone.localdate()).strftime("%Y/%m/%d")
    shift_segment = instance.pk or "nouveau"
    employee_segment = instance.employe_id or "employee"
    return f"pointages/{date_str}/{employee_segment}/{shift_segment}/{filename}"


class DailyQRToken(models.Model):
    """
    QR Code du jour par site - Système de sécurité pour les pointages
    """
    site = models.ForeignKey("sites.Location", on_delete=models.CASCADE, verbose_name="Site")
    date = models.DateField(verbose_name="Date")
    nonce = models.CharField(max_length=32, verbose_name="Nonce")
    token = models.CharField(max_length=64, unique=True, verbose_name="Token")
    actif = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    regenerated_at = models.DateTimeField(null=True, blank=True, verbose_name="Régénéré le")
    regenerated_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name="qr_regenerations",
        verbose_name="Régénéré par"
    )
    
    class Meta:
        verbose_name = "QR Token du Jour"
        verbose_name_plural = "QR Tokens du Jour"
        unique_together = [["site", "date", "actif"]]
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["site", "date", "actif"]),
            models.Index(fields=["token"]),
        ]
    
    def __str__(self):
        return f"{self.site.nom} - {self.date} - {'Actif' if self.actif else 'Inactif'}"
    
    @classmethod
    def generate_token(cls, site_id, date_str, nonce):
        """
        Générer un token sécurisé avec HMAC-SHA256
        """
        from django.conf import settings
        secret = settings.QR_SECRET_KEY
        data = f"{site_id}|{date_str}|{nonce}"
        return hashlib.sha256(f"{secret}:{data}".encode()).hexdigest()
    
    @classmethod
    def create_daily_qr(cls, site, date=None, created_by=None):
        """
        Créer un nouveau QR du jour pour un site
        """
        if date is None:
            date = timezone.localdate()
        
        # Désactiver les anciens QR de ce site pour cette date
        cls.objects.filter(site=site, date=date, actif=True).update(actif=False)
        
        # Générer un nouveau token
        nonce = secrets.token_hex(16)
        token = cls.generate_token(str(site.id), str(date), nonce)
        
        qr_token = cls.objects.create(
            site=site,
            date=date,
            nonce=nonce,
            token=token,
            actif=True
        )
        
        return qr_token
    
    def get_qr_payload(self):
        """
        Obtenir le payload JSON pour le QR code
        """
        return json.dumps({
            "v": 1,
            "site_id": str(self.site.id),
            "date": str(self.date),
            "nonce": self.nonce,
            "token": self.token
        })
    
    @classmethod
    def validate_qr_scan(cls, payload_json, employee_site=None):
        """
        Valider un scan de QR code
        Retourne (valid: bool, message: str, qr_token: DailyQRToken or None)
        """
        try:
            payload = json.loads(payload_json)
            site_id = payload.get("site_id")
            date_str = payload.get("date")
            token = payload.get("token")
            
            # Vérifier que la date est aujourd'hui
            today = timezone.localdate()
            if str(today) != date_str:
                return False, "QR invalide ou expiré.", None
            
            # Chercher le token
            try:
                qr_token = cls.objects.get(
                    site__id=site_id,
                    date=date_str,
                    token=token,
                    actif=True
                )
            except cls.DoesNotExist:
                return False, "QR invalide ou expiré.", None
            
            # Vérifier que l'employé est sur le bon site (si employee_site fourni)
            if employee_site and str(qr_token.site.id) != str(employee_site.id):
                return False, "Ce QR appartient à un autre site.", None
            
            return True, "QR valide", qr_token
            
        except (json.JSONDecodeError, KeyError):
            return False, "Format de QR invalide.", None


class ShiftDay(models.Model):
    """
    Pointage d'un employé (entrée et sortie)
    """
    GPS_STATUS_CHOICES = [
        ("OK", "OK"),
        ("HORS_ZONE", "Hors zone"),
        ("INCONNU", "Inconnu"),
    ]
    
    employe = models.ForeignKey(User, on_delete=models.CASCADE, related_name="pointages", verbose_name="Employé")
    site = models.ForeignKey("sites.Location", on_delete=models.CASCADE, verbose_name="Site")
    date = models.DateField(verbose_name="Date")
    
    # Pointage entrée
    clock_in_time = models.DateTimeField(null=True, blank=True, verbose_name="Heure d'entrée")
    clock_in_photo = models.ImageField(
        upload_to=attendance_photo_path,
        blank=True,
        null=True,
        verbose_name="Photo de début de journée",
    )
    clock_in_photo_taken_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Photo entrée prise à",
    )
    
    # Pointage sortie
    clock_out_time = models.DateTimeField(null=True, blank=True, verbose_name="Heure de sortie")
    clock_out_photo = models.ImageField(
        upload_to=attendance_photo_path,
        blank=True,
        null=True,
        verbose_name="Photo de fin de journée",
    )
    clock_out_photo_taken_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Photo sortie prise à",
    )
    
    # GPS pour entrée
    clock_in_gps_latitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Latitude GPS (entrée)"
    )
    clock_in_gps_longitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Longitude GPS (entrée)"
    )
    clock_in_gps_distance_mètres = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        verbose_name="Distance GPS (entrée, mètres)"
    )
    clock_in_gps_status = models.CharField(
        max_length=20,
        choices=GPS_STATUS_CHOICES,
        default="INCONNU",
        verbose_name="Statut GPS (entrée)"
    )
    
    # GPS pour sortie
    clock_out_gps_latitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Latitude GPS (sortie)"
    )
    clock_out_gps_longitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Longitude GPS (sortie)"
    )
    clock_out_gps_distance_mètres = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        verbose_name="Distance GPS (sortie, mètres)"
    )
    clock_out_gps_status = models.CharField(
        max_length=20,
        choices=GPS_STATUS_CHOICES,
        default="INCONNU",
        verbose_name="Statut GPS (sortie)"
    )
    
    # Rapport de fin de journée
    daily_report_confirmed = models.BooleanField(default=False, verbose_name="Rapport confirmé")
    total_lavages_reported = models.IntegerField(default=0, verbose_name="Total lavages déclaré")
    total_amount_reported_fc = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Montant total déclaré (FC)",
    )
    lavages_review = models.TextField(blank=True, verbose_name="Revue des lavages")
    problems_review = models.TextField(blank=True, verbose_name="Revue des problèmes")
    report_notes = models.TextField(blank=True, verbose_name="Notes du rapport")
    daily_expenses = models.JSONField(default=list, blank=True, verbose_name="Depenses du jour")
    daily_expenses_total_fc = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Total depenses du jour (FC)",
    )
    
    # Corrections (manager)
    corrected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pointages_corriges",
        verbose_name="Corrigé par"
    )
    correction_reason = models.TextField(blank=True, verbose_name="Motif de correction")
    corrected_at = models.DateTimeField(null=True, blank=True, verbose_name="Corrigé le")
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Pointage"
        verbose_name_plural = "Pointages"
        unique_together = [["employe", "date"]]
        ordering = ["-date", "-clock_in_time"]
        indexes = [
            models.Index(fields=["employe", "date"]),
            models.Index(fields=["site", "date"]),
            models.Index(fields=["site", "date", "daily_report_confirmed"], name="pointage_site_date_report_idx"),
            models.Index(fields=["employe", "-updated_at"], name="pointage_employe_updated_idx"),
            models.Index(fields=["-created_at"], name="pointage_created_desc_idx"),
        ]
    
    def __str__(self):
        return f"{self.employe.get_full_name() or self.employe.username} - {self.date}"

    @property
    def daily_expense_items(self):
        expense_items = []
        for item in self.daily_expenses or []:
            label = str(item.get("label", "")).strip()
            if not label:
                continue

            try:
                amount_fc = Decimal(str(item.get("amount_fc", "0")))
            except (ArithmeticError, InvalidOperation, TypeError, ValueError):
                amount_fc = Decimal("0")

            if amount_fc < 0:
                amount_fc = Decimal("0")

            expense_items.append({
                "key": str(item.get("key", "")).strip(),
                "label": label,
                "amount_fc": amount_fc,
                "is_known": bool(item.get("is_known")),
            })

        return expense_items

    @property
    def daily_expense_summary(self):
        items = self.daily_expense_items
        if not items:
            return "Aucune depense confirmee."

        return " • ".join(
            f"{item['label']}: {item['amount_fc']:,.0f} FC".replace(",", " ")
            for item in items
        )
    
    def is_complete(self):
        """Vérifie si le pointage est complet (entrée ET sortie)"""
        return self.clock_out_time is not None
    
    def duration(self):
        """Calcule la durée du shift si complet"""
        if self.is_complete():
            return self.clock_out_time - self.clock_in_time
        return None
    
    def has_missed_punch(self):
        """Vérifie si il manque un pointage de sortie"""
        return self.clock_out_time is None

    @property
    def clock_in_photo_thumbnail_url(self):
        return get_thumbnail_url(self.clock_in_photo)

    @property
    def clock_out_photo_thumbnail_url(self):
        return get_thumbnail_url(self.clock_out_photo)

    def get_clock_in_attendance_status(self, *, reference_time=None):
        return get_clock_in_status(self.date, self.clock_in_time, reference_time=reference_time)

    def get_clock_out_attendance_status(self, *, reference_time=None):
        return get_clock_out_status(self.date, self.clock_out_time, reference_time=reference_time)

    def save(self, *args, **kwargs):
        if self.clock_in_photo and not self.clock_in_photo._committed:
            self.clock_in_photo = optimize_image_upload(self.clock_in_photo)
        if self.clock_out_photo and not self.clock_out_photo._committed:
            self.clock_out_photo = optimize_image_upload(self.clock_out_photo)

        super().save(*args, **kwargs)

        if self.clock_in_photo:
            ensure_image_thumbnail(self.clock_in_photo)
        if self.clock_out_photo:
            ensure_image_thumbnail(self.clock_out_photo)
