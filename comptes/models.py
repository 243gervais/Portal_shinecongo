from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    """
    Profil utilisateur étendu avec rôle et site
    """
    ROLE_CHOICES = [
        ("EMPLOYE", "Employé"),
        ("MANAGER", "Manager"),
        ("ADMIN", "Administrateur"),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="userprofile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="EMPLOYE", verbose_name="Rôle")
    site = models.ForeignKey("sites.Location", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Site")
    telephone = models.CharField(max_length=20, blank=True, verbose_name="Téléphone")
    actif = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Profil Utilisateur"
        verbose_name_plural = "Profils Utilisateurs"
        ordering = ["-created_at"]
    
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.get_role_display()}"
    
    def is_employe(self):
        return self.role == "EMPLOYE"
    
    def is_manager(self):
        return self.role == "MANAGER"
    
    def is_admin(self):
        return self.role == "ADMIN"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Créer automatiquement un profil quand un utilisateur est créé
    """
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """
    Sauvegarder le profil quand l'utilisateur est sauvegardé
    """
    if hasattr(instance, "userprofile"):
        instance.userprofile.save()
