from django.db import models
from django.contrib.auth.models import User
import os


def issue_photo_path(instance, filename):
    """Chemin de sauvegarde des photos de problème"""
    date_str = instance.created_at.strftime("%Y/%m/%d")
    return f"problemes/{date_str}/{instance.id}/{filename}"


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
            models.Index(fields=["-created_at"]),
        ]
    
    def __str__(self):
        return f"{self.get_categorie_display()} - {self.employe.username} - {self.created_at.strftime('%Y-%m-%d')}"
    
    def is_ouvert(self):
        return self.statut == "OUVERT"
    
    def is_resolu(self):
        return self.statut == "RESOLU"
