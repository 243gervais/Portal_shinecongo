from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.utils import timezone
import os

from comptes.image_utils import ensure_image_thumbnail, get_thumbnail_url, optimize_image_upload


def carwash_photo_path(instance, filename):
    """Chemin de sauvegarde des photos de lavage"""
    date_str = instance.lavage.created_at.strftime("%Y/%m/%d")
    return f"lavages/{date_str}/{instance.lavage.id}/{filename}"


def plaque_photo_path(instance, filename):
    """Chemin de sauvegarde des photos de plaque"""
    date_str = timezone.now().strftime("%Y/%m/%d")
    return f"lavages/plaques/{date_str}/{filename}"


class CarWash(models.Model):
    """
    Enregistrement d'un lavage de voiture
    """
    TYPE_SERVICE_CHOICES = [
        ("COMPLET", "Lavage Complet"),
        ("EXTERIEUR", "Lavage Extérieur"),
        ("INTERIEUR", "Lavage Intérieur"),
        ("EXPRESS", "Lavage Express"),
        ("PREMIUM", "Lavage Premium"),
    ]
    
    employe = models.ForeignKey(User, on_delete=models.CASCADE, related_name="lavages", verbose_name="Employé")
    site = models.ForeignKey("sites.Location", on_delete=models.CASCADE, verbose_name="Site")
    date = models.DateField(verbose_name="Date")
    
    # Détails du service
    type_service = models.CharField(
        max_length=20, 
        choices=TYPE_SERVICE_CHOICES, 
        default="COMPLET",
        verbose_name="Type de service"
    )
    plaque = models.CharField(max_length=50, blank=True, verbose_name="Numéro de plaque")
    plaque_photo = models.ImageField(
        upload_to=plaque_photo_path,
        blank=True,
        null=True,
        verbose_name="Photo de la plaque",
    )
    montant = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Montant payé (FC)"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    is_system_generated = models.BooleanField(
        default=False,
        verbose_name="Généré automatiquement",
    )
    system_source = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Source système",
    )
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Lavage"
        verbose_name_plural = "Lavages"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["employe", "date"]),
            models.Index(fields=["site", "date"]),
            models.Index(fields=["employe", "-created_at"], name="lavages_employe_created_idx"),
            models.Index(fields=["site", "-created_at"], name="lavages_site_created_idx"),
            models.Index(fields=["is_system_generated", "system_source"]),
            models.Index(fields=["-created_at"]),
        ]
    
    def __str__(self):
        return f"{self.get_type_service_display()} - {self.employe.username} - {self.date}"
    
    def photo_count(self):
        """Nombre de photos associées"""
        annotated_count = getattr(self, "photo_count_value", None)
        if annotated_count is not None:
            return annotated_count
        return self.photos.count()

    @property
    def plaque_photo_thumbnail_url(self):
        return get_thumbnail_url(self.plaque_photo)

    def save(self, *args, **kwargs):
        if self.plaque_photo and not self.plaque_photo._committed:
            self.plaque_photo = optimize_image_upload(self.plaque_photo)
        super().save(*args, **kwargs)
        if self.plaque_photo:
            ensure_image_thumbnail(self.plaque_photo)


class CarWashPhoto(models.Model):
    """
    Photo d'un lavage (avant/après)
    """
    PHOTO_TYPE_CHOICES = [
        ("AVANT", "Avant"),
        ("APRES", "Après"),
        ("AUTRE", "Autre"),
    ]
    
    lavage = models.ForeignKey(CarWash, on_delete=models.CASCADE, related_name="photos", verbose_name="Lavage")
    photo = models.ImageField(upload_to=carwash_photo_path, verbose_name="Photo")
    type_photo = models.CharField(
        max_length=10,
        choices=PHOTO_TYPE_CHOICES,
        default="AUTRE",
        verbose_name="Type de photo"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="Uploadé le")
    
    class Meta:
        verbose_name = "Photo de Lavage"
        verbose_name_plural = "Photos de Lavage"
        ordering = ["type_photo", "uploaded_at"]
        indexes = [
            models.Index(fields=["lavage", "-uploaded_at"], name="lavage_photo_uploaded_idx"),
        ]
    
    def __str__(self):
        return f"Photo {self.get_type_photo_display()} - {self.lavage}"
    
    def filename(self):
        """Retourne le nom du fichier"""
        return os.path.basename(self.photo.name)

    @property
    def thumbnail_url(self):
        return get_thumbnail_url(self.photo)

    def save(self, *args, **kwargs):
        if self.photo and not self.photo._committed:
            self.photo = optimize_image_upload(self.photo)
        super().save(*args, **kwargs)
        if self.photo:
            ensure_image_thumbnail(self.photo)
