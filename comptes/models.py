from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
import os


def employee_cv_upload_path(instance, filename):
    """
    Chemin de stockage des CV employés.
    """
    ext = os.path.splitext(filename)[1].lower()
    safe_ext = ext if ext else ".pdf"
    return f"employees/{instance.user_id}/cv{safe_ext}"


def employee_photo_upload_path(instance, filename):
    """
    Chemin de stockage de la photo profil employé.
    """
    ext = os.path.splitext(filename)[1].lower()
    safe_ext = ext if ext else ".jpg"
    return f"employees/{instance.user_id}/photo{safe_ext}"


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
    mpesa_numero = models.CharField(max_length=30, blank=True, verbose_name="Numéro M-Pesa")
    date_embauche = models.DateField(null=True, blank=True, verbose_name="Date d'embauche")
    salaire_mensuel_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name="Salaire mensuel (USD)",
    )
    cv_file = models.FileField(
        upload_to=employee_cv_upload_path,
        null=True,
        blank=True,
        verbose_name="CV employé",
    )
    profile_photo = models.ImageField(
        upload_to=employee_photo_upload_path,
        null=True,
        blank=True,
        verbose_name="Photo employé",
    )
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

    def anciennete_jours(self):
        if not self.date_embauche:
            return None
        return max((timezone.localdate() - self.date_embauche).days, 0)

    def anciennete_texte(self):
        days = self.anciennete_jours()
        if days is None:
            return "Non renseignée"
        years = days // 365
        months = (days % 365) // 30
        if years > 0:
            return f"{years} an(s) et {months} mois"
        if months > 0:
            return f"{months} mois"
        return f"{days} jour(s)"

    def cv_filename(self):
        if not self.cv_file:
            return ""
        return os.path.basename(self.cv_file.name)

    def photo_filename(self):
        if not self.profile_photo:
            return ""
        return os.path.basename(self.profile_photo.name)


class EmployeePayment(models.Model):
    """
    Historique des paiements de salaire des employés.
    """

    PAYMENT_METHOD_CHOICES = [
        ("MPESA", "M-Pesa"),
        ("ESPECES", "Espèces"),
        ("BANQUE", "Virement bancaire"),
    ]

    employee_profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="salary_payments",
        verbose_name="Employé",
    )
    site = models.ForeignKey("sites.Location", on_delete=models.CASCADE, related_name="employee_payments", verbose_name="Site")
    payment_date = models.DateField(default=timezone.localdate, verbose_name="Date de paiement")
    period_start = models.DateField(verbose_name="Période du")
    period_end = models.DateField(verbose_name="Période au")
    salary_base_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Salaire de base (USD)",
    )
    amount_paid_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Montant payé (USD)",
    )
    payment_method = models.CharField(
        max_length=15,
        choices=PAYMENT_METHOD_CHOICES,
        default="MPESA",
        verbose_name="Mode de paiement",
    )
    mpesa_reference = models.CharField(max_length=100, blank=True, verbose_name="Référence M-Pesa")
    employee_signature_name = models.CharField(max_length=150, verbose_name="Signature employé (nom)")
    signed_at = models.DateTimeField(default=timezone.now, verbose_name="Signé le")
    admin_signature_name = models.CharField(max_length=150, verbose_name="Signature admin")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_payments_created",
        verbose_name="Créé par",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")

    class Meta:
        verbose_name = "Paiement Employé"
        verbose_name_plural = "Paiements Employés"
        ordering = ["-payment_date", "-created_at"]
        indexes = [
            models.Index(fields=["site", "payment_date"]),
            models.Index(fields=["employee_profile", "payment_date"]),
        ]

    def __str__(self):
        employee_name = self.employee_profile.user.get_full_name() or self.employee_profile.user.username
        return f"{employee_name} - {self.amount_paid_usd} USD ({self.payment_date})"


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
