from datetime import date as python_date

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
import os

from comptes.image_utils import ensure_image_thumbnail, get_thumbnail_url, optimize_image_upload


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
    EMPLOYEE_ROLE = "EMPLOYE"
    CAMERA_CONTROLLER_ROLE = "CONTROLE_CAMERA"
    MANAGER_ROLE = "MANAGER"
    ADMIN_ROLE = "ADMIN"
    SITE_STAFF_ROLES = [EMPLOYEE_ROLE, CAMERA_CONTROLLER_ROLE]

    ROLE_CHOICES = [
        (EMPLOYEE_ROLE, "Employé"),
        (CAMERA_CONTROLLER_ROLE, "Contrôle caméra"),
        (MANAGER_ROLE, "Manager"),
        (ADMIN_ROLE, "Administrateur"),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="userprofile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="EMPLOYE", verbose_name="Rôle")
    site = models.ForeignKey("sites.Location", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Site")
    telephone = models.CharField(max_length=20, blank=True, verbose_name="Téléphone")
    mpesa_numero = models.CharField(max_length=30, blank=True, verbose_name="Numéro M-Pesa")
    date_embauche = models.DateField(null=True, blank=True, verbose_name="Date d'embauche")
    date_naissance = models.DateField(null=True, blank=True, verbose_name="Date de naissance")
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
    password_reference = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Mot de passe mémorisé",
        help_text="Référence visible uniquement dans la page admin Gestion des mots de passe.",
    )
    admin_requests_last_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Dernière consultation des demandes admin",
    )
    admin_reports_last_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Dernière consultation des rapports admin",
    )
    admin_messages_last_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Dernière consultation des messages admin",
    )
    actif = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Profil Utilisateur"
        verbose_name_plural = "Profils Utilisateurs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "role", "actif"], name="cp_prof_site_role_actif_ix"),
            models.Index(fields=["role", "actif"], name="cp_prof_role_actif_ix"),
            models.Index(fields=["-created_at"], name="cp_prof_created_desc_ix"),
        ]
    
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.get_role_display()}"
    
    def is_employe(self):
        return self.role == self.EMPLOYEE_ROLE

    def is_camera_controller(self):
        return self.role == self.CAMERA_CONTROLLER_ROLE

    def is_site_staff(self):
        return self.role in self.SITE_STAFF_ROLES
    
    def is_manager(self):
        return self.role == self.MANAGER_ROLE
    
    def is_admin(self):
        return self.role == self.ADMIN_ROLE

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

    @property
    def has_password_reference(self):
        return bool((self.password_reference or "").strip())

    def set_password_reference(self, raw_password, save=True):
        self.password_reference = (raw_password or "").strip()
        if save:
            self.save(update_fields=["password_reference", "updated_at"])

    @property
    def profile_photo_thumbnail_url(self):
        return get_thumbnail_url(self.profile_photo)

    def prochaine_date_anniversaire(self, reference_date=None):
        if not self.date_naissance:
            return None
        reference = reference_date or timezone.localdate()
        birth_month = self.date_naissance.month
        birth_day = self.date_naissance.day

        def _build_candidate(year):
            try:
                return python_date(year, birth_month, birth_day)
            except ValueError:
                return python_date(year, 2, 28)

        candidate = _build_candidate(reference.year)
        if candidate < reference:
            candidate = _build_candidate(reference.year + 1)
        return candidate

    def jours_avant_anniversaire(self, reference_date=None):
        reference = reference_date or timezone.localdate()
        prochain = self.prochaine_date_anniversaire(reference)
        if not prochain:
            return None
        return max((prochain - reference).days, 0)

    def save(self, *args, **kwargs):
        if self.profile_photo and not self.profile_photo._committed:
            self.profile_photo = optimize_image_upload(self.profile_photo)
        super().save(*args, **kwargs)
        if self.profile_photo:
            ensure_image_thumbnail(self.profile_photo)


class AdminReminder(models.Model):
    """
    Rappels globaux visibles dans la Boite Admin pour le portail et le site web.
    """

    TARGET_CHOICES = [
        ("PORTAL", "Portail"),
        ("WEBSITE", "Site web shinecongo.org"),
    ]

    PRIORITY_CHOICES = [
        ("INFO", "Information"),
        ("IMPORTANT", "Important"),
        ("URGENT", "Urgent"),
    ]

    title = models.CharField(max_length=200, verbose_name="Titre")
    description = models.TextField(blank=True, verbose_name="Détails")
    target = models.CharField(
        max_length=20,
        choices=TARGET_CHOICES,
        default="PORTAL",
        verbose_name="Cible",
    )
    priority = models.CharField(
        max_length=12,
        choices=PRIORITY_CHOICES,
        default="IMPORTANT",
        verbose_name="Priorité",
    )
    due_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Échéance",
        help_text="Optionnel. Utilisez-le pour faire remonter un rappel à une date précise.",
    )
    is_resolved = models.BooleanField(default=False, verbose_name="Traité")
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="Traité le")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_reminders_created",
        verbose_name="Créé par",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Rappel Admin"
        verbose_name_plural = "Rappels Admin"
        ordering = ["is_resolved", "due_at", "-created_at"]
        indexes = [
            models.Index(fields=["is_resolved", "due_at"]),
            models.Index(fields=["target", "priority"]),
        ]

    def __str__(self):
        return f"{self.get_target_display()} - {self.title}"


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
