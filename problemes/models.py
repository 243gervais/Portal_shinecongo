from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import os

from comptes.image_utils import ensure_image_thumbnail, get_thumbnail_url, optimize_image_upload


def issue_photo_path(instance, filename):
    """Chemin de sauvegarde des photos de problème"""
    reference_time = instance.created_at or timezone.now()
    date_str = reference_time.strftime("%Y/%m/%d")
    issue_segment = instance.id or "nouveau"
    return f"problemes/{date_str}/{issue_segment}/{filename}"


class IssueReport(models.Model):
    """
    Rapport de problème signalé par un employé
    """
    CATEGORIE_CHOICES = [
        ("MATERIEL", "Matériel"),
        ("EAU", "Eau"),
        ("CLIENT", "Client"),
        ("SECURITE", "Sécurité"),
        ("AUTRE", "Autre"),
    ]
    
    STATUT_CHOICES = [
        ("OUVERT", "Ouvert"),
        ("EN_COURS", "En cours"),
        ("RESOLU", "Résolu"),
    ]
    
    employe = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name="problemes_signales",
        verbose_name="Signalé par"
    )
    site = models.ForeignKey("sites.Location", on_delete=models.CASCADE, verbose_name="Site")
    categorie = models.CharField(max_length=20, choices=CATEGORIE_CHOICES, verbose_name="Catégorie")
    description = models.TextField(verbose_name="Description")
    photo = models.ImageField(upload_to=issue_photo_path, blank=True, null=True, verbose_name="Photo (optionnel)")
    
    # Statut et traitement
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default="OUVERT", verbose_name="Statut")
    traite_par = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="problemes_traites",
        verbose_name="Traité par"
    )
    notes_resolution = models.TextField(blank=True, verbose_name="Notes de résolution")
    resolu_le = models.DateTimeField(null=True, blank=True, verbose_name="Résolu le")
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Signalé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Problème Signalé"
        verbose_name_plural = "Problèmes Signalés"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "statut"]),
            models.Index(fields=["site", "statut", "-created_at"], name="issue_site_statut_created_idx"),
            models.Index(fields=["employe", "-created_at"], name="issue_employe_created_idx"),
            models.Index(fields=["-created_at"]),
        ]
    
    def __str__(self):
        return f"{self.get_categorie_display()} - {self.employe.username} - {self.created_at.strftime('%Y-%m-%d')}"
    
    def is_ouvert(self):
        return self.statut == "OUVERT"
    
    def is_resolu(self):
        return self.statut == "RESOLU"

    @property
    def photo_thumbnail_url(self):
        return get_thumbnail_url(self.photo)

    def save(self, *args, **kwargs):
        if self.photo and not self.photo._committed:
            self.photo = optimize_image_upload(self.photo)
        super().save(*args, **kwargs)
        if self.photo:
            ensure_image_thumbnail(self.photo)
