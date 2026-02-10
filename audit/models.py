from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class AuditLog(models.Model):
    """
    Journal d'audit pour tracer toutes les actions importantes
    """
    ACTION_CHOICES = [
        ("CREER", "Créer"),
        ("MODIFIER", "Modifier"),
        ("SUPPRIMER", "Supprimer"),
        ("CORRIGER_POINTAGE", "Corriger Pointage"),
        ("REGENERER_QR", "Régénérer QR"),
        ("CHANGER_STATUT", "Changer Statut"),
        ("LOGIN", "Connexion"),
        ("LOGOUT", "Déconnexion"),
        ("AUTRE", "Autre"),
    ]
    
    # Qui a fait l'action
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="Utilisateur")
    
    # Quelle action
    action = models.CharField(max_length=30, choices=ACTION_CHOICES, verbose_name="Action")
    description = models.TextField(verbose_name="Description")
    
    # Sur quel objet (optionnel, via GenericForeignKey)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Type de contenu"
    )
    object_id = models.PositiveIntegerField(null=True, blank=True, verbose_name="ID de l'objet")
    content_object = GenericForeignKey("content_type", "object_id")
    
    # Détails supplémentaires
    motif = models.TextField(blank=True, verbose_name="Motif")
    donnees_avant = models.JSONField(null=True, blank=True, verbose_name="Données avant")
    donnees_apres = models.JSONField(null=True, blank=True, verbose_name="Données après")
    
    # Métadonnées
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="Adresse IP")
    user_agent = models.TextField(blank=True, verbose_name="User Agent")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Entrée d'Audit"
        verbose_name_plural = "Journal d'Audit"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]
    
    def __str__(self):
        username = self.user.username if self.user else "Système"
        return f"{username} - {self.get_action_display()} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
    
    @classmethod
    def log(cls, user, action, description, motif="", content_object=None, donnees_avant=None, donnees_apres=None, ip_address=None, user_agent=""):
        """
        Créer une entrée dans le journal d'audit
        """
        log_entry = cls.objects.create(
            user=user,
            action=action,
            description=description,
            motif=motif,
            content_object=content_object,
            donnees_avant=donnees_avant,
            donnees_apres=donnees_apres,
            ip_address=ip_address,
            user_agent=user_agent
        )
        return log_entry
