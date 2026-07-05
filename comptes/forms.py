from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.db.models import Q
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.text import slugify

from shinecongo.currency import convert_cdf_to_usd, get_usd_to_cdf_rate
from sites.models import (
    Camera,
    DailyCameraReport,
    DEFAULT_WATER_SUPPLIER_NAME,
    DEFAULT_WATER_SUPPLIER_RATE_FC,
    Location,
    SiteDocument,
    SiteFuelPurchase,
    SiteJournalEntry,
    SiteWaterPurchase,
    VideoEvidence,
    WaterSupplier,
    get_default_water_supplier,
)

from .models import AdminReminder, EmployeePayment, UserProfile
from .recruitment import build_candidate_dossier_pdf, get_reviewed_candidate_cv_choices


CV_ALLOWED_EXTENSIONS = (".pdf", ".doc", ".docx")
CV_ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
CV_MAX_SIZE_BYTES = 10 * 1024 * 1024


def _validate_uploaded_cv_file(cv_file):
    filename = (cv_file.name or "").lower()
    if not filename.endswith(CV_ALLOWED_EXTENSIONS):
        raise forms.ValidationError("Format CV non supporté. Utilisez PDF, DOC ou DOCX.")
    if cv_file.size > CV_MAX_SIZE_BYTES:
        raise forms.ValidationError("Le CV dépasse la limite de 10 MB.")
    return cv_file


def _is_shinecongo_host(hostname):
    normalized = (hostname or "").strip().lower()
    return normalized == "shinecongo.org" or normalized == "www.shinecongo.org" or normalized.endswith(".shinecongo.org")


def _build_cv_filename(source_name, content_type):
    safe_source_name = os.path.basename((source_name or "").strip())
    base_name, extension = os.path.splitext(safe_source_name)
    normalized_extension = extension.lower()
    if normalized_extension not in CV_ALLOWED_EXTENSIONS:
        normalized_extension = CV_ALLOWED_CONTENT_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if normalized_extension not in CV_ALLOWED_EXTENSIONS:
        raise forms.ValidationError("Le lien choisi doit pointer vers un CV PDF, DOC ou DOCX.")
    safe_base_name = slugify(base_name) or "cv-employe"
    return f"{safe_base_name}{normalized_extension}"


def _download_cv_from_url(cv_source_url, invalid_link_message):
    parsed_url = urlparse(cv_source_url)
    if parsed_url.scheme not in {"http", "https"} or not _is_shinecongo_host(parsed_url.hostname):
        raise forms.ValidationError(invalid_link_message)

    request = Request(
        cv_source_url,
        headers={"User-Agent": "ShineCongoPortal/1.0"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            response_info = response.info()
            content_type = response_info.get_content_type() if response_info else ""
            source_name = ""
            if response_info:
                source_name = response_info.get_filename() or ""
            if not source_name:
                source_name = os.path.basename(parsed_url.path)

            filename = _build_cv_filename(source_name, content_type)
            file_bytes = response.read(CV_MAX_SIZE_BYTES + 1)
    except forms.ValidationError:
        raise
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        raise forms.ValidationError("Impossible de récupérer le CV depuis shinecongo.org pour le moment.")

    if len(file_bytes) > CV_MAX_SIZE_BYTES:
        raise forms.ValidationError("Le CV dépasse la limite de 10 MB.")

    return ContentFile(file_bytes, name=filename)


def get_water_purchase_default_supplier():
    return get_default_water_supplier()


def _resolve_water_supplier(supplier=None):
    if isinstance(supplier, WaterSupplier):
        return supplier
    if supplier:
        resolved_supplier = WaterSupplier.objects.filter(pk=supplier).first()
        if resolved_supplier:
            return resolved_supplier
    return get_water_purchase_default_supplier()


def get_water_purchase_default_amount(target_month=None, supplier=None):
    resolved_supplier = _resolve_water_supplier(supplier)
    if resolved_supplier:
        return resolved_supplier.price_per_tank_fc
    return DEFAULT_WATER_SUPPLIER_RATE_FC


def get_water_purchase_amount_help_text(target_month=None, supplier=None):
    resolved_supplier = _resolve_water_supplier(supplier)
    supplier_name = resolved_supplier.name if resolved_supplier else DEFAULT_WATER_SUPPLIER_NAME
    suggested_amount = get_water_purchase_default_amount(supplier=resolved_supplier)
    return (
        f"Montant suggéré : {suggested_amount:,.0f} FC pour un remplissage du citerne "
        f"avec {supplier_name}. Vous pouvez toujours le modifier si nécessaire."
    ).replace(",", " ")


class ApprovalAuthenticationForm(AuthenticationForm):
    """
    Authentication form that shows a clear message when an account is pending approval.
    """

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username and password:
            inactive_user = User.objects.filter(username=username, is_active=False).first()
            if inactive_user and inactive_user.check_password(password):
                raise forms.ValidationError(
                    "Votre compte est en attente d'approbation par l'administrateur.",
                    code="inactive",
                )

        return super().clean()

    def confirm_login_allowed(self, user):
        if not user.is_active:
            raise forms.ValidationError(
                "Votre compte est en attente d'approbation par l'administrateur.",
                code="inactive",
            )
        super().confirm_login_allowed(user)


class SiteChoiceField(forms.ModelChoiceField):
    """Display site name and address in registration dropdown choices."""

    def label_from_instance(self, obj):
        adresse = obj.adresse.strip() if obj.adresse else "Adresse non renseignée"
        return f"{obj.nom} — {adresse}"


class UserRegistrationForm(UserCreationForm):
    """
    Formulaire d'inscription pour créer un nouveau compte utilisateur
    """
    username = forms.CharField(
        label="Identifiant",
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Entrez votre identifiant',
            'autofocus': True
        })
    )
    password1 = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Entrez votre mot de passe',
            'minlength': '4'
        }),
        help_text="Le mot de passe doit contenir au moins 4 caractères."
    )
    password2 = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirmez votre mot de passe',
            'minlength': '4'
        })
    )
    site = SiteChoiceField(
        label="Site",
        queryset=Location.objects.none(),
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control',
        }),
        help_text="Sélectionnez votre site dans la liste existante."
    )
    telephone = forms.CharField(
        label="Téléphone",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Votre numéro de téléphone (optionnel)'
        })
    )
    
    class Meta:
        model = User
        fields = ("username", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sites = Location.objects.filter(actif=True).order_by("nom")
        self.fields["site"].queryset = sites
        self.fields["site"].empty_label = "Sélectionnez votre site"
        if not sites.exists():
            self.fields["site"].help_text = "Aucun site actif disponible. Contactez un administrateur."
    
    def clean_username(self):
        username = self.cleaned_data.get("username")
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Cet identifiant est déjà utilisé. Veuillez en choisir un autre.")
        return username
    
    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Les mots de passe ne correspondent pas.")
        return password2
    
    def save(self, commit=True):
        user = super().save(commit=False)
        # New accounts must be explicitly approved by an administrator.
        user.is_active = False
        if commit:
            user.save()
            # Le profil sera créé automatiquement via le signal post_save
            # Mettre à jour le profil avec le téléphone et le site
            profile = user.userprofile
            profile.telephone = self.cleaned_data.get('telephone', '')
            profile.actif = False
            profile.site = self.cleaned_data.get('site')
            profile.role = "EMPLOYE"  # Par défaut, nouveau utilisateur = Employé
            profile.password_reference = self.cleaned_data.get("password1", "")
            profile.save()
        
        return user


class SiteCreationForm(forms.ModelForm):
    """
    Form for creating a site from the custom admin dashboard.
    """

    class Meta:
        model = Location
        fields = [
            "nom",
            "adresse",
            "ville",
            "telephone",
            "gps_actif",
            "latitude",
            "longitude",
            "rayon_autorisé_mètres",
            "actif",
        ]
        widgets = {
            "nom": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom du site"}),
            "adresse": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Adresse (optionnel)"}),
            "ville": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ville"}),
            "telephone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Téléphone (optionnel)"}),
            "gps_actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "latitude": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001", "placeholder": "Latitude"}),
            "longitude": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001", "placeholder": "Longitude"}),
            "rayon_autorisé_mètres": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        gps_actif = cleaned_data.get("gps_actif")
        latitude = cleaned_data.get("latitude")
        longitude = cleaned_data.get("longitude")

        if gps_actif and (latitude is None or longitude is None):
            raise forms.ValidationError("Si le GPS est actif, la latitude et la longitude sont obligatoires.")

        return cleaned_data


class SiteEmployeeForm(forms.Form):
    """
    Création / mise à jour d'un membre rattaché à un site.
    """

    role = forms.ChoiceField(
        label="Rôle du compte",
        choices=[
            (UserProfile.EMPLOYEE_ROLE, "Employé lavage"),
            (UserProfile.CAMERA_CONTROLLER_ROLE, "Contrôle caméra"),
        ],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    username = forms.CharField(
        label="Identifiant",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Identifiant de connexion"}),
    )
    first_name = forms.CharField(
        label="Prénom",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        label="Nom",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="Email",
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "email@exemple.com"}),
    )
    telephone = forms.CharField(
        label="Téléphone",
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    mpesa_numero = forms.CharField(
        label="Numéro M-Pesa",
        required=False,
        max_length=30,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    date_embauche = forms.DateField(
        label="Date d'embauche",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    date_naissance = forms.DateField(
        label="Date de naissance",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    salaire_mensuel_usd = forms.DecimalField(
        label="Salaire mensuel (USD)",
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=12,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    cv_file = forms.FileField(
        label="CV de l'employé",
        required=False,
        help_text="Optionnel. Ajoutez un CV local en PDF, DOC ou DOCX.",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
        ),
    )
    reviewed_cv_source = forms.ChoiceField(
        label="CV enregistré sur shinecongo.org",
        required=False,
        help_text="Optionnel. Sélectionnez un CV déjà enregistré sur shinecongo.org. Les CV revus apparaissent en priorité. Si aucun fichier CV n'est joint côté site, le portail génère un dossier PDF depuis la fiche candidature.",
        widget=forms.Select(
            attrs={
                "class": "form-control",
            }
        ),
        choices=[("", "Sélectionnez un CV du site (optionnel)")],
    )
    profile_photo = forms.ImageField(
        label="Photo de l'employé",
        required=False,
        help_text="Optionnel. Ajoutez une photo pour la fiche employé.",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp",
            }
        ),
    )
    password = forms.CharField(
        label="Mot de passe",
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        help_text="Obligatoire à la création. Laissez vide en modification pour conserver le mot de passe actuel.",
    )
    is_active = forms.BooleanField(
        label="Compte actif",
        required=False,
        initial=True,
    )

    def __init__(self, *args, user_instance=None, profile_instance=None, initial_role=None, **kwargs):
        self.user_instance = user_instance
        self.profile_instance = profile_instance
        super().__init__(*args, **kwargs)
        self.reviewed_candidate_choices = get_reviewed_candidate_cv_choices()
        self.reviewed_candidate_choices_by_id = {
            choice.external_id: choice for choice in self.reviewed_candidate_choices if choice.external_id
        }

        preset_role = initial_role or self.initial.get("role") or UserProfile.EMPLOYEE_ROLE
        self.fields["role"].initial = preset_role
        if self.reviewed_candidate_choices:
            self.fields["reviewed_cv_source"].choices = [
                ("", "Sélectionnez un CV du site (optionnel)"),
                *[(choice.external_id, choice.label) for choice in self.reviewed_candidate_choices],
            ]
        else:
            self.fields["reviewed_cv_source"].choices = [
                ("", "Aucun CV du site disponible pour le moment"),
            ]
            self.fields["reviewed_cv_source"].help_text = (
                "Aucun CV déjà enregistré avec fichier joint n'est actuellement disponible depuis shinecongo.org."
            )
        if self.user_instance:
            self.fields["username"].initial = self.user_instance.username
            self.fields["first_name"].initial = self.user_instance.first_name
            self.fields["last_name"].initial = self.user_instance.last_name
            self.fields["email"].initial = self.user_instance.email
            self.fields["is_active"].initial = self.user_instance.is_active
        if self.profile_instance:
            self.fields["role"].initial = self.profile_instance.role
            self.fields["telephone"].initial = self.profile_instance.telephone
            self.fields["mpesa_numero"].initial = self.profile_instance.mpesa_numero
            self.fields["date_embauche"].initial = self.profile_instance.date_embauche
            self.fields["date_naissance"].initial = self.profile_instance.date_naissance
            self.fields["salaire_mensuel_usd"].initial = self.profile_instance.salaire_mensuel_usd

    def clean_username(self):
        username = self.cleaned_data["username"]
        query = User.objects.filter(username=username)
        if self.user_instance:
            query = query.exclude(id=self.user_instance.id)
        if query.exists():
            raise forms.ValidationError("Cet identifiant est déjà utilisé.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email", "")
        if not email:
            return email
        query = User.objects.filter(email=email)
        if self.user_instance:
            query = query.exclude(id=self.user_instance.id)
        if query.exists():
            raise forms.ValidationError("Cet email est déjà utilisé.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if not self.user_instance and not password:
            raise forms.ValidationError("Le mot de passe est obligatoire à la création.")
        return password

    def clean_cv_file(self):
        cv_file = self.cleaned_data.get("cv_file")
        if not cv_file:
            return cv_file
        return _validate_uploaded_cv_file(cv_file)

    def clean_role(self):
        role = self.cleaned_data["role"]
        allowed_roles = {UserProfile.EMPLOYEE_ROLE, UserProfile.CAMERA_CONTROLLER_ROLE}
        if role not in allowed_roles:
            raise forms.ValidationError("Choisissez un rôle valide pour ce compte.")
        return role

    def clean(self):
        cleaned_data = super().clean()
        cv_file = cleaned_data.get("cv_file")
        reviewed_cv_source = (cleaned_data.get("reviewed_cv_source") or "").strip()

        if cv_file and reviewed_cv_source:
            raise forms.ValidationError(
                "Choisissez soit un fichier CV local, soit un CV déjà enregistré sur shinecongo.org, mais pas les deux."
            )

        if reviewed_cv_source:
            selected_candidate = self.reviewed_candidate_choices_by_id.get(reviewed_cv_source)
            if not selected_candidate:
                raise forms.ValidationError("Le CV sélectionné n'est plus disponible. Rechargez la page puis réessayez.")
            if selected_candidate.cv_url:
                cleaned_data["resolved_cv_file"] = _download_cv_from_url(
                    selected_candidate.cv_url,
                    "Le CV sélectionné doit provenir de shinecongo.org.",
                )
            else:
                cleaned_data["resolved_cv_file"] = build_candidate_dossier_pdf(selected_candidate)

        return cleaned_data

    def save(self, site):
        if self.user_instance:
            user = self.user_instance
        else:
            user = User()

        user.username = self.cleaned_data["username"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data.get("email", "")
        user.is_active = self.cleaned_data.get("is_active", True)

        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        elif not user.pk:
            user.set_unusable_password()

        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = self.cleaned_data["role"]
        profile.site = site
        profile.telephone = self.cleaned_data.get("telephone", "")
        profile.mpesa_numero = self.cleaned_data.get("mpesa_numero", "")
        profile.date_embauche = self.cleaned_data.get("date_embauche")
        profile.date_naissance = self.cleaned_data.get("date_naissance")
        profile.salaire_mensuel_usd = self.cleaned_data.get("salaire_mensuel_usd")
        if password:
            profile.password_reference = password
        resolved_cv_file = self.cleaned_data.get("resolved_cv_file") or self.cleaned_data.get("cv_file")
        if resolved_cv_file:
            if profile.cv_file:
                profile.cv_file.delete(save=False)
            profile.cv_file = resolved_cv_file
        profile_photo = self.cleaned_data.get("profile_photo")
        if profile_photo:
            profile.profile_photo = profile_photo
        profile.actif = user.is_active
        profile.save()
        return profile


class AdminReminderForm(forms.ModelForm):
    due_at = forms.DateTimeField(
        label="Échéance",
        required=False,
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        help_text="Optionnel. Heure de Kinshasa recommandée pour les rappels sensibles.",
    )

    class Meta:
        model = AdminReminder
        fields = ["target", "priority", "title", "description", "due_at"]
        widgets = {
            "target": forms.Select(attrs={"class": "form-control"}),
            "priority": forms.Select(attrs={"class": "form-control"}),
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex: Préparer le contenu de shinecongo.org",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Détail du rappel ou de la notification.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.due_at:
            self.initial["due_at"] = timezone.localtime(self.instance.due_at).strftime("%Y-%m-%dT%H:%M")

    def clean_due_at(self):
        due_at = self.cleaned_data.get("due_at")
        if due_at and timezone.is_naive(due_at):
            due_at = timezone.make_aware(due_at, timezone.get_current_timezone())
        return due_at


class AdminPasswordManagementForm(forms.Form):
    """
    Formulaire simple pour permettre à un admin de redéfinir un mot de passe.
    """

    new_password1 = forms.CharField(
        label="Nouveau mot de passe",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Nouveau mot de passe",
                "autocomplete": "new-password",
                "minlength": "4",
            }
        ),
        help_text="Minimum 4 caractères.",
    )
    new_password2 = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Confirmez le mot de passe",
                "autocomplete": "new-password",
                "minlength": "4",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("new_password1")
        password2 = cleaned_data.get("new_password2")

        if password1 and len(password1) < 4:
            self.add_error("new_password1", "Le mot de passe doit contenir au moins 4 caractères.")

        if password1 and password2 and password1 != password2:
            self.add_error("new_password2", "Les mots de passe ne correspondent pas.")

        return cleaned_data

    def save(self, user):
        user.set_password(self.cleaned_data["new_password1"])
        user.save(update_fields=["password"])
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.set_password_reference(self.cleaned_data["new_password1"])
        return user


class AdminPasswordReferenceForm(forms.Form):
    """
    Formulaire admin pour mémoriser visiblement un mot de passe sans le changer réellement.
    """

    password_reference = forms.CharField(
        label="Mot de passe visible",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Saisissez le mot de passe à mémoriser",
                "autocomplete": "off",
            }
        ),
        help_text="Ce mémo ne change pas le vrai mot de passe du compte.",
    )

    def clean_password_reference(self):
        return (self.cleaned_data.get("password_reference") or "").strip()


class EmployeePaymentForm(forms.Form):
    """
    Enregistrer un paiement employé et générer la fiche de paiement.
    """

    payment_date = forms.DateField(
        label="Date de paiement",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    period_start = forms.DateField(
        label="Période du",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    period_end = forms.DateField(
        label="Période au",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    amount_paid_usd = forms.DecimalField(
        label="Montant payé (USD)",
        min_value=0,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    payment_method = forms.ChoiceField(
        label="Mode de paiement",
        choices=EmployeePayment.PAYMENT_METHOD_CHOICES,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    mpesa_reference = forms.CharField(
        label="Référence M-Pesa",
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    employee_signature_name = forms.CharField(
        label="Signature employé (nom complet)",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    notes = forms.CharField(
        label="Notes",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def __init__(self, *args, employee_profile=None, **kwargs):
        self.employee_profile = employee_profile
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        month_start = today.replace(day=1)
        self.fields["payment_date"].initial = today
        self.fields["period_start"].initial = month_start
        self.fields["period_end"].initial = today
        salaire = getattr(employee_profile, "salaire_mensuel_usd", None)
        if salaire is not None:
            self.fields["amount_paid_usd"].initial = salaire

    def clean(self):
        cleaned_data = super().clean()
        period_start = cleaned_data.get("period_start")
        period_end = cleaned_data.get("period_end")
        payment_method = cleaned_data.get("payment_method")
        mpesa_reference = cleaned_data.get("mpesa_reference", "").strip()

        if period_start and period_end and period_start > period_end:
            raise forms.ValidationError("La date de début de période doit être antérieure à la date de fin.")

        if payment_method == "MPESA" and not mpesa_reference:
            raise forms.ValidationError("La référence M-Pesa est obligatoire pour un paiement M-Pesa.")

        return cleaned_data


class SiteJournalEntryForm(forms.ModelForm):
    amount_usd = forms.DecimalField(
        label="Montant lié (USD)",
        required=False,
        min_value=Decimal("0"),
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
    )
    reminder_at = forms.DateTimeField(
        label="Rappel par email",
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            attrs={"class": "form-control", "type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
    )

    def __init__(self, *args, reminder_user=None, **kwargs):
        self.reminder_user = reminder_user
        super().__init__(*args, **kwargs)
        self.default_reminder_email = self._resolve_reminder_email()
        rate_data = get_usd_to_cdf_rate()
        self.usd_to_cdf_rate = Decimal(str(rate_data.get("usd_to_cdf") or "0"))
        if self.usd_to_cdf_rate <= 0:
            self.usd_to_cdf_rate = Decimal("1")
        self.fx_rate_label = f"1 USD = {self.usd_to_cdf_rate.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,.0f} FC".replace(",", " ")

        if self.instance and self.instance.pk and self.instance.reminder_at:
            self.initial["reminder_at"] = timezone.localtime(self.instance.reminder_at).strftime("%Y-%m-%dT%H:%M")
        if self.instance and self.instance.pk and self.instance.amount_fc:
            conversion = convert_cdf_to_usd(self.instance.amount_fc)
            self.initial["amount_usd"] = conversion["amount_usd"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if self.default_reminder_email:
            self.fields["reminder_at"].help_text = (
                f"Optionnel. Si vous choisissez une date et une heure, un email sera envoyé à "
                f"{self.default_reminder_email} (heure de Kinshasa)."
            )
        else:
            self.fields["reminder_at"].help_text = (
                "Optionnel. Ajoutez un email à votre compte administrateur pour recevoir ce rappel."
            )

        amount_help_text = (
            "Optionnel. Entrez le montant en FC ou en USD. Le portail convertit automatiquement avec le taux du jour "
            f"({self.fx_rate_label})."
        )
        self.fields["amount_fc"].help_text = amount_help_text
        self.fields["amount_usd"].help_text = amount_help_text
        self.fields["amount_fc"].widget.attrs["data-journal-fx"] = "fc"
        self.fields["amount_usd"].widget.attrs["data-journal-fx"] = "usd"

    def _resolve_reminder_email(self):
        candidates = [
            getattr(self.reminder_user, "email", ""),
            getattr(self.instance, "reminder_email", ""),
            getattr(settings, "FINAL_REPORT_NOTIFICATION_EMAIL", ""),
            getattr(settings, "EMAIL_HOST_USER", ""),
        ]
        for value in candidates:
            email = str(value or "").strip()
            if email:
                return email
        return ""

    class Meta:
        model = SiteJournalEntry
        fields = ["entry_date", "category", "title", "description", "amount_fc", "reminder_at"]
        widgets = {
            "entry_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "category": forms.Select(attrs={"class": "form-control"}),
            "title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex: Achat matériel, visite du site, décision à retenir"}
            ),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 4, "placeholder": "Décrivez ce qui a été fait, constaté ou payé"}
            ),
            "amount_fc": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
        }
        help_texts = {
            "amount_fc": "Optionnel. Ce montant reste informatif et n'entre pas automatiquement dans les calculs financiers.",
        }

    def clean_reminder_at(self):
        reminder_at = self.cleaned_data.get("reminder_at")
        if reminder_at and timezone.is_naive(reminder_at):
            reminder_at = timezone.make_aware(reminder_at, timezone.get_current_timezone())
        return reminder_at

    def clean(self):
        cleaned_data = super().clean()
        amount_fc = cleaned_data.get("amount_fc")
        amount_usd = cleaned_data.get("amount_usd")
        reminder_at = cleaned_data.get("reminder_at")

        if amount_fc is None and amount_usd is not None:
            cleaned_data["amount_fc"] = (amount_usd * self.usd_to_cdf_rate).quantize(Decimal("0.01"))
        elif amount_fc is not None:
            cleaned_data["amount_usd"] = (amount_fc / self.usd_to_cdf_rate).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

        if not reminder_at:
            return cleaned_data

        if not self._resolve_reminder_email():
            self.add_error(
                "reminder_at",
                "Ajoutez un email valide à votre compte administrateur pour programmer un rappel.",
            )
            return cleaned_data

        reminder_is_already_sent = bool(
            self.instance
            and self.instance.pk
            and self.instance.reminder_sent_at
            and self.instance.reminder_at == reminder_at
        )

        if reminder_at <= timezone.now() and not reminder_is_already_sent:
            self.add_error(
                "reminder_at",
                "Choisissez une date et une heure futures (heure de Kinshasa).",
            )

        return cleaned_data

    def save(self, commit=True):
        entry = super().save(commit=False)
        reminder_email = self._resolve_reminder_email()
        previous_reminder_at = self.instance.reminder_at if self.instance and self.instance.pk else None
        previous_reminder_email = self.instance.reminder_email if self.instance and self.instance.pk else ""

        if entry.reminder_at:
            entry.reminder_email = reminder_email
            if previous_reminder_at != entry.reminder_at or previous_reminder_email != entry.reminder_email:
                entry.reminder_sent_at = None
        else:
            entry.reminder_email = ""
            entry.reminder_sent_at = None

        if commit:
            entry.save()

        return entry


class SiteJournalEntryMoveForm(forms.Form):
    """
    Formulaire dédié à la migration d'une entrée du journal vers une autre catégorie/date.
    """

    entry_date = forms.DateField(
        label="Nouvelle date",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    category = forms.ChoiceField(
        label="Nouvelle catégorie",
        choices=SiteJournalEntry.CATEGORY_CHOICES,
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, entry_instance=None, **kwargs):
        self.entry_instance = entry_instance
        super().__init__(*args, **kwargs)

        if self.entry_instance:
            self.fields["entry_date"].initial = self.entry_instance.entry_date
            self.fields["category"].initial = self.entry_instance.category

    def save(self, entry):
        entry.entry_date = self.cleaned_data["entry_date"]
        entry.category = self.cleaned_data["category"]
        entry.save(update_fields=["entry_date", "category", "updated_at"])
        return entry


class SiteDocumentMoveForm(forms.Form):
    """
    Formulaire dédié à la migration d'un document vers une autre section documentaire.
    """

    file_type = forms.ChoiceField(
        label="Nouvelle section",
        choices=SiteDocument.FILE_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, document_instance=None, **kwargs):
        self.document_instance = document_instance
        super().__init__(*args, **kwargs)

        if self.document_instance and not self.is_bound:
            self.fields["file_type"].initial = self.document_instance.file_type

    def save(self, document):
        document.file_type = self.cleaned_data["file_type"]
        document.save(update_fields=["file_type", "updated_at"])
        return document


class SiteWaterPurchaseMoveForm(forms.Form):
    ASSIGNMENT_SCOPE_CHOICES = [
        ("GENERAL", "General du mois"),
        ("WEEK", "Affecter a une semaine"),
    ]

    billing_month = forms.DateField(
        label="Nouveau mois concerne",
        input_formats=["%Y-%m"],
        widget=forms.DateInput(
            format="%Y-%m",
            attrs={"class": "form-control", "type": "month"},
        ),
    )
    assignment_scope = forms.ChoiceField(
        label="Imputation dans le mois",
        choices=ASSIGNMENT_SCOPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-control"}),
        help_text="Choisissez General du mois pour sortir cet achat du detail hebdomadaire, ou une semaine precise pour le rattacher a un bloc hebdomadaire.",
    )
    reporting_week_date = forms.DateField(
        label="Jour de la semaine cible",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        help_text="Choisissez n'importe quel jour de la semaine cible dans le mois concerne.",
    )

    def __init__(self, *args, purchase_instance=None, **kwargs):
        self.purchase_instance = purchase_instance
        super().__init__(*args, **kwargs)

        if self.purchase_instance and not self.is_bound:
            effective_reporting_date = self.purchase_instance.get_reporting_week_date()
            self.fields["billing_month"].initial = self.purchase_instance.billing_month
            self.fields["assignment_scope"].initial = "WEEK" if effective_reporting_date else "GENERAL"
            self.fields["reporting_week_date"].initial = effective_reporting_date

    def clean_billing_month(self):
        billing_month = self.cleaned_data["billing_month"]
        return billing_month.replace(day=1)

    def clean(self):
        cleaned_data = super().clean()
        billing_month = cleaned_data.get("billing_month")
        assignment_scope = cleaned_data.get("assignment_scope")
        reporting_week_date = cleaned_data.get("reporting_week_date")

        if assignment_scope == "WEEK":
            if not reporting_week_date:
                self.add_error(
                    "reporting_week_date",
                    "Choisissez un jour dans la semaine cible pour rattacher cet achat.",
                )
            elif (
                billing_month
                and (
                    reporting_week_date.year != billing_month.year
                    or reporting_week_date.month != billing_month.month
                )
            ):
                self.add_error(
                    "reporting_week_date",
                    "La semaine choisie doit appartenir au mois concerne.",
                )
        else:
            cleaned_data["reporting_week_date"] = None

        return cleaned_data

    def save(self, purchase):
        purchase.billing_month = self.cleaned_data["billing_month"]
        purchase.reporting_week_date = self.cleaned_data.get("reporting_week_date")
        purchase.save(update_fields=["billing_month", "reporting_week_date", "updated_at"])
        return purchase


class WaterSupplierForm(forms.ModelForm):
    class Meta:
        model = WaterSupplier
        fields = ["name", "price_per_tank_fc", "is_default", "is_active", "notes"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex: Forage Kintambo"}
            ),
            "price_per_tank_fc": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
            "is_default": forms.CheckboxInput(),
            "is_active": forms.CheckboxInput(),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optionnel: zone desservie, contact, consignes de paiement...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.is_bound:
            self.fields["is_active"].initial = True

    def clean(self):
        cleaned_data = super().clean()
        is_active = cleaned_data.get("is_active")
        other_active_suppliers = WaterSupplier.objects.exclude(pk=self.instance.pk).filter(is_active=True)

        if is_active is False and not other_active_suppliers.exists():
            self.add_error(
                "is_active",
                "Gardez au moins un fournisseur actif pour continuer à enregistrer les achats d'eau.",
            )

        return cleaned_data


class SiteWaterPurchaseForm(forms.ModelForm):
    billing_month = forms.DateField(
        label="Mois concerné",
        help_text="Sélectionnez le mois auquel cet achat d'eau doit être rattaché.",
        input_formats=["%Y-%m"],
        widget=forms.DateInput(
            format="%Y-%m",
            attrs={"class": "form-control", "type": "month"},
        ),
    )

    class Meta:
        model = SiteWaterPurchase
        fields = ["site", "supplier", "billing_month", "purchase_date", "amount_fc", "notes"]
        widgets = {
            "site": forms.Select(attrs={"class": "form-control"}),
            "supplier": forms.Select(attrs={"class": "form-control"}),
            "purchase_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "amount_fc": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "notes": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "placeholder": "Optionnel: remarque sur le remplissage ou le transport"}
            ),
        }
        help_texts = {
            "amount_fc": "",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_month = timezone.localdate().replace(day=1)
        selected_month = self._resolve_selected_month(current_month)
        default_supplier = get_water_purchase_default_supplier()
        supplier_queryset = WaterSupplier.objects.filter(is_active=True)
        if self.instance and self.instance.pk and self.instance.supplier_id:
            supplier_queryset = WaterSupplier.objects.filter(
                Q(is_active=True) | Q(pk=self.instance.supplier_id)
            )
        supplier_queryset = supplier_queryset.order_by("-is_default", "name")
        self.fields["site"].queryset = Location.objects.filter(actif=True).order_by("nom")
        self.fields["supplier"].queryset = supplier_queryset
        self.fields["supplier"].required = False
        selected_supplier = self._resolve_selected_supplier(default_supplier)
        if not self.is_bound:
            self.fields["billing_month"].initial = selected_month
            self.fields["purchase_date"].initial = self.initial.get("purchase_date") or timezone.localdate()
            self.fields["supplier"].initial = (
                self.instance.supplier if self.instance and self.instance.pk else selected_supplier
            )
            if self.instance and self.instance.pk:
                self.fields["amount_fc"].initial = self.instance.amount_fc
            else:
                self.fields["amount_fc"].initial = get_water_purchase_default_amount(
                    selected_month,
                    supplier=selected_supplier,
                )

        self.fields["amount_fc"].help_text = get_water_purchase_amount_help_text(
            selected_month,
            supplier=selected_supplier,
        )

        if self.instance and self.instance.pk and self.instance.billing_month:
            self.initial["billing_month"] = self.instance.billing_month
        if self.instance and self.instance.pk and self.instance.supplier_id:
            self.initial["supplier"] = self.instance.supplier

    def clean_billing_month(self):
        billing_month = self.cleaned_data["billing_month"]
        return billing_month.replace(day=1)

    def clean_supplier(self):
        supplier = self.cleaned_data.get("supplier")
        return supplier or get_water_purchase_default_supplier()

    def _resolve_selected_month(self, fallback_month):
        if self.instance and self.instance.pk and self.instance.billing_month:
            return self.instance.billing_month.replace(day=1)

        raw_month = self.data.get("billing_month") if self.is_bound else self.initial.get("billing_month")
        if hasattr(raw_month, "replace") and not isinstance(raw_month, str):
            return raw_month.replace(day=1)
        if isinstance(raw_month, str) and raw_month:
            try:
                return datetime.strptime(raw_month, "%Y-%m").date().replace(day=1)
            except ValueError:
                try:
                    return datetime.strptime(raw_month, "%Y-%m-%d").date().replace(day=1)
                except ValueError:
                    return fallback_month
        return fallback_month

    def _resolve_selected_supplier(self, fallback_supplier):
        if self.instance and self.instance.pk and self.instance.supplier_id:
            return self.instance.supplier

        raw_supplier = self.data.get("supplier") if self.is_bound else self.initial.get("supplier")
        resolved_supplier = _resolve_water_supplier(raw_supplier)
        return resolved_supplier or fallback_supplier


class SiteFuelPurchaseForm(forms.ModelForm):
    billing_month = forms.DateField(
        label="Mois concerné",
        help_text="Sélectionnez le mois auquel cet achat de carburant doit être rattaché.",
        input_formats=["%Y-%m"],
        widget=forms.DateInput(
            format="%Y-%m",
            attrs={"class": "form-control", "type": "month"},
        ),
    )

    class Meta:
        model = SiteFuelPurchase
        fields = ["site", "billing_month", "purchase_date", "amount_fc", "notes"]
        widgets = {
            "site": forms.Select(attrs={"class": "form-control"}),
            "purchase_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "amount_fc": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optionnel: motif de l'achat, équipement concerné, ou précision utile",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        selected_month = self._resolve_selected_month(timezone.localdate().replace(day=1))
        self.fields["site"].queryset = Location.objects.filter(actif=True).order_by("nom")

        if not self.is_bound:
            self.fields["billing_month"].initial = selected_month
            self.fields["purchase_date"].initial = self.initial.get("purchase_date") or timezone.localdate()
            if self.instance and self.instance.pk:
                self.fields["amount_fc"].initial = self.instance.amount_fc

        if self.instance and self.instance.pk and self.instance.billing_month:
            self.initial["billing_month"] = self.instance.billing_month

    def clean_billing_month(self):
        billing_month = self.cleaned_data["billing_month"]
        return billing_month.replace(day=1)

    def _resolve_selected_month(self, fallback_month):
        if self.instance and self.instance.pk and self.instance.billing_month:
            return self.instance.billing_month.replace(day=1)

        raw_month = self.data.get("billing_month") if self.is_bound else self.initial.get("billing_month")
        if hasattr(raw_month, "replace") and not isinstance(raw_month, str):
            return raw_month.replace(day=1)
        if isinstance(raw_month, str) and raw_month:
            try:
                return datetime.strptime(raw_month, "%Y-%m").date().replace(day=1)
            except ValueError:
                try:
                    return datetime.strptime(raw_month, "%Y-%m-%d").date().replace(day=1)
                except ValueError:
                    return fallback_month
        return fallback_month


class CameraForm(forms.ModelForm):
    class Meta:
        model = Camera
        fields = [
            "name",
            "camera_number",
            "camera_position",
            "app_name",
            "notes",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Caméra entrée principale"}),
            "camera_number": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "camera_position": forms.Select(attrs={"class": "form-control"}),
            "app_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: V380, Hik-Connect..."}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Remarques d'installation, angle, accès..."}),
            "is_active": forms.CheckboxInput(),
        }


class DailyCameraReportForm(forms.ModelForm):
    class Meta:
        model = DailyCameraReport
        fields = [
            "date",
            "cars_count",
            "motos_count",
            "three_wheelers_count",
            "notes",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "cars_count": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "motos_count": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "three_wheelers_count": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Notes sur le comptage, le trafic, une anomalie ou une précision terrain.",
                }
            ),
        }
        help_texts = {
            "cars_count": "Prix voiture: 15 000 FC",
            "motos_count": "Prix moto (2 pneus): 3 000 FC",
            "three_wheelers_count": "Prix moto à 3 pneus: 5 000 FC",
        }


class VideoEvidenceForm(forms.ModelForm):
    class Meta:
        model = VideoEvidence
        fields = [
            "camera",
            "title",
            "evidence_type",
            "clip_date",
            "start_time",
            "end_time",
            "uploaded_file",
            "notes",
        ]
        widgets = {
            "camera": forms.Select(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Clip entrée 08h15"}),
            "evidence_type": forms.Select(attrs={"class": "form-control"}),
            "clip_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "start_time": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "end_time": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "uploaded_file": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": "video/*,image/*,.mp4,.mov,.avi,.mkv,.webm,.jpg,.jpeg,.png,.webp",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Expliquez pourquoi ce clip ou cette capture doit être conservé.",
                }
            ),
        }

    def __init__(self, *args, site=None, daily_report=None, **kwargs):
        self.site = site or getattr(daily_report, "site", None)
        self.daily_report = daily_report
        super().__init__(*args, **kwargs)

        if self.site:
            self.fields["camera"].queryset = Camera.objects.filter(site=self.site).order_by("camera_number", "name")
        else:
            self.fields["camera"].queryset = Camera.objects.none()

        if self.daily_report and not self.is_bound:
            self.fields["clip_date"].initial = self.daily_report.date

    def clean(self):
        cleaned_data = super().clean()
        camera = cleaned_data.get("camera")
        if camera and self.site and camera.site_id != self.site.id:
            self.add_error("camera", "Choisissez une caméra du site concerné.")
        return cleaned_data
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.db.models import Q
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.text import slugify

from shinecongo.currency import convert_cdf_to_usd, get_usd_to_cdf_rate
from sites.models import (
    Camera,
    DailyCameraReport,
    DEFAULT_WATER_SUPPLIER_NAME,
    DEFAULT_WATER_SUPPLIER_RATE_FC,
    Location,
    SiteDocument,
    SiteJournalEntry,
    SiteWaterPurchase,
    VideoEvidence,
    WaterSupplier,
    get_default_water_supplier,
)

from .models import AdminReminder, EmployeePayment, UserProfile
from .recruitment import build_candidate_dossier_pdf, get_reviewed_candidate_cv_choices


CV_ALLOWED_EXTENSIONS = (".pdf", ".doc", ".docx")
CV_ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
CV_MAX_SIZE_BYTES = 10 * 1024 * 1024


def _validate_uploaded_cv_file(cv_file):
    filename = (cv_file.name or "").lower()
    if not filename.endswith(CV_ALLOWED_EXTENSIONS):
        raise forms.ValidationError("Format CV non supporté. Utilisez PDF, DOC ou DOCX.")
    if cv_file.size > CV_MAX_SIZE_BYTES:
        raise forms.ValidationError("Le CV dépasse la limite de 10 MB.")
    return cv_file


def _is_shinecongo_host(hostname):
    normalized = (hostname or "").strip().lower()
    return normalized == "shinecongo.org" or normalized == "www.shinecongo.org" or normalized.endswith(".shinecongo.org")


def _build_cv_filename(source_name, content_type):
    safe_source_name = os.path.basename((source_name or "").strip())
    base_name, extension = os.path.splitext(safe_source_name)
    normalized_extension = extension.lower()
    if normalized_extension not in CV_ALLOWED_EXTENSIONS:
        normalized_extension = CV_ALLOWED_CONTENT_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if normalized_extension not in CV_ALLOWED_EXTENSIONS:
        raise forms.ValidationError("Le lien choisi doit pointer vers un CV PDF, DOC ou DOCX.")
    safe_base_name = slugify(base_name) or "cv-employe"
    return f"{safe_base_name}{normalized_extension}"


def _download_cv_from_url(cv_source_url, invalid_link_message):
    parsed_url = urlparse(cv_source_url)
    if parsed_url.scheme not in {"http", "https"} or not _is_shinecongo_host(parsed_url.hostname):
        raise forms.ValidationError(invalid_link_message)

    request = Request(
        cv_source_url,
        headers={"User-Agent": "ShineCongoPortal/1.0"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            response_info = response.info()
            content_type = response_info.get_content_type() if response_info else ""
            source_name = ""
            if response_info:
                source_name = response_info.get_filename() or ""
            if not source_name:
                source_name = os.path.basename(parsed_url.path)

            filename = _build_cv_filename(source_name, content_type)
            file_bytes = response.read(CV_MAX_SIZE_BYTES + 1)
    except forms.ValidationError:
        raise
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        raise forms.ValidationError("Impossible de récupérer le CV depuis shinecongo.org pour le moment.")

    if len(file_bytes) > CV_MAX_SIZE_BYTES:
        raise forms.ValidationError("Le CV dépasse la limite de 10 MB.")

    return ContentFile(file_bytes, name=filename)


def get_water_purchase_default_supplier():
    return get_default_water_supplier()


def _resolve_water_supplier(supplier=None):
    if isinstance(supplier, WaterSupplier):
        return supplier
    if supplier:
        resolved_supplier = WaterSupplier.objects.filter(pk=supplier).first()
        if resolved_supplier:
            return resolved_supplier
    return get_water_purchase_default_supplier()


def get_water_purchase_default_amount(target_month=None, supplier=None):
    resolved_supplier = _resolve_water_supplier(supplier)
    if resolved_supplier:
        return resolved_supplier.price_per_tank_fc
    return DEFAULT_WATER_SUPPLIER_RATE_FC


def get_water_purchase_amount_help_text(target_month=None, supplier=None):
    resolved_supplier = _resolve_water_supplier(supplier)
    supplier_name = resolved_supplier.name if resolved_supplier else DEFAULT_WATER_SUPPLIER_NAME
    suggested_amount = get_water_purchase_default_amount(supplier=resolved_supplier)
    return (
        f"Montant suggéré : {suggested_amount:,.0f} FC pour un remplissage du citerne "
        f"avec {supplier_name}. Vous pouvez toujours le modifier si nécessaire."
    ).replace(",", " ")


class ApprovalAuthenticationForm(AuthenticationForm):
    """
    Authentication form that shows a clear message when an account is pending approval.
    """

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username and password:
            inactive_user = User.objects.filter(username=username, is_active=False).first()
            if inactive_user and inactive_user.check_password(password):
                raise forms.ValidationError(
                    "Votre compte est en attente d'approbation par l'administrateur.",
                    code="inactive",
                )

        return super().clean()

    def confirm_login_allowed(self, user):
        if not user.is_active:
            raise forms.ValidationError(
                "Votre compte est en attente d'approbation par l'administrateur.",
                code="inactive",
            )
        super().confirm_login_allowed(user)


class SiteChoiceField(forms.ModelChoiceField):
    """Display site name and address in registration dropdown choices."""

    def label_from_instance(self, obj):
        adresse = obj.adresse.strip() if obj.adresse else "Adresse non renseignée"
        return f"{obj.nom} — {adresse}"


class UserRegistrationForm(UserCreationForm):
    """
    Formulaire d'inscription pour créer un nouveau compte utilisateur
    """
    username = forms.CharField(
        label="Identifiant",
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Entrez votre identifiant',
            'autofocus': True
        })
    )
    password1 = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Entrez votre mot de passe',
            'minlength': '4'
        }),
        help_text="Le mot de passe doit contenir au moins 4 caractères."
    )
    password2 = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirmez votre mot de passe',
            'minlength': '4'
        })
    )
    site = SiteChoiceField(
        label="Site",
        queryset=Location.objects.none(),
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control',
        }),
        help_text="Sélectionnez votre site dans la liste existante."
    )
    telephone = forms.CharField(
        label="Téléphone",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Votre numéro de téléphone (optionnel)'
        })
    )
    
    class Meta:
        model = User
        fields = ("username", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sites = Location.objects.filter(actif=True).order_by("nom")
        self.fields["site"].queryset = sites
        self.fields["site"].empty_label = "Sélectionnez votre site"
        if not sites.exists():
            self.fields["site"].help_text = "Aucun site actif disponible. Contactez un administrateur."
    
    def clean_username(self):
        username = self.cleaned_data.get("username")
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Cet identifiant est déjà utilisé. Veuillez en choisir un autre.")
        return username
    
    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Les mots de passe ne correspondent pas.")
        return password2
    
    def save(self, commit=True):
        user = super().save(commit=False)
        # New accounts must be explicitly approved by an administrator.
        user.is_active = False
        if commit:
            user.save()
            # Le profil sera créé automatiquement via le signal post_save
            # Mettre à jour le profil avec le téléphone et le site
            profile = user.userprofile
            profile.telephone = self.cleaned_data.get('telephone', '')
            profile.actif = False
            profile.site = self.cleaned_data.get('site')
            profile.role = "EMPLOYE"  # Par défaut, nouveau utilisateur = Employé
            profile.password_reference = self.cleaned_data.get("password1", "")
            profile.save()
        
        return user


class SiteCreationForm(forms.ModelForm):
    """
    Form for creating a site from the custom admin dashboard.
    """

    class Meta:
        model = Location
        fields = [
            "nom",
            "adresse",
            "ville",
            "telephone",
            "gps_actif",
            "latitude",
            "longitude",
            "rayon_autorisé_mètres",
            "actif",
        ]
        widgets = {
            "nom": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom du site"}),
            "adresse": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Adresse (optionnel)"}),
            "ville": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ville"}),
            "telephone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Téléphone (optionnel)"}),
            "gps_actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "latitude": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001", "placeholder": "Latitude"}),
            "longitude": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001", "placeholder": "Longitude"}),
            "rayon_autorisé_mètres": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        gps_actif = cleaned_data.get("gps_actif")
        latitude = cleaned_data.get("latitude")
        longitude = cleaned_data.get("longitude")

        if gps_actif and (latitude is None or longitude is None):
            raise forms.ValidationError("Si le GPS est actif, la latitude et la longitude sont obligatoires.")

        return cleaned_data


class SiteEmployeeForm(forms.Form):
    """
    Création / mise à jour d'un membre rattaché à un site.
    """

    role = forms.ChoiceField(
        label="Rôle du compte",
        choices=[
            (UserProfile.EMPLOYEE_ROLE, "Employé lavage"),
            (UserProfile.CAMERA_CONTROLLER_ROLE, "Contrôle caméra"),
        ],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    username = forms.CharField(
        label="Identifiant",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Identifiant de connexion"}),
    )
    first_name = forms.CharField(
        label="Prénom",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        label="Nom",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="Email",
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "email@exemple.com"}),
    )
    telephone = forms.CharField(
        label="Téléphone",
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    mpesa_numero = forms.CharField(
        label="Numéro M-Pesa",
        required=False,
        max_length=30,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    date_embauche = forms.DateField(
        label="Date d'embauche",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    date_naissance = forms.DateField(
        label="Date de naissance",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    salaire_mensuel_usd = forms.DecimalField(
        label="Salaire mensuel (USD)",
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=12,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    cv_file = forms.FileField(
        label="CV de l'employé",
        required=False,
        help_text="Optionnel. Ajoutez un CV local en PDF, DOC ou DOCX.",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
        ),
    )
    reviewed_cv_source = forms.ChoiceField(
        label="CV enregistré sur shinecongo.org",
        required=False,
        help_text="Optionnel. Sélectionnez un CV déjà enregistré sur shinecongo.org. Les CV revus apparaissent en priorité. Si aucun fichier CV n'est joint côté site, le portail génère un dossier PDF depuis la fiche candidature.",
        widget=forms.Select(
            attrs={
                "class": "form-control",
            }
        ),
        choices=[("", "Sélectionnez un CV du site (optionnel)")],
    )
    profile_photo = forms.ImageField(
        label="Photo de l'employé",
        required=False,
        help_text="Optionnel. Ajoutez une photo pour la fiche employé.",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp",
            }
        ),
    )
    password = forms.CharField(
        label="Mot de passe",
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        help_text="Obligatoire à la création. Laissez vide en modification pour conserver le mot de passe actuel.",
    )
    is_active = forms.BooleanField(
        label="Compte actif",
        required=False,
        initial=True,
    )

    def __init__(self, *args, user_instance=None, profile_instance=None, initial_role=None, **kwargs):
        self.user_instance = user_instance
        self.profile_instance = profile_instance
        super().__init__(*args, **kwargs)
        self.reviewed_candidate_choices = get_reviewed_candidate_cv_choices()
        self.reviewed_candidate_choices_by_id = {
            choice.external_id: choice for choice in self.reviewed_candidate_choices if choice.external_id
        }

        preset_role = initial_role or self.initial.get("role") or UserProfile.EMPLOYEE_ROLE
        self.fields["role"].initial = preset_role
        if self.reviewed_candidate_choices:
            self.fields["reviewed_cv_source"].choices = [
                ("", "Sélectionnez un CV du site (optionnel)"),
                *[(choice.external_id, choice.label) for choice in self.reviewed_candidate_choices],
            ]
        else:
            self.fields["reviewed_cv_source"].choices = [
                ("", "Aucun CV du site disponible pour le moment"),
            ]
            self.fields["reviewed_cv_source"].help_text = (
                "Aucun CV déjà enregistré avec fichier joint n'est actuellement disponible depuis shinecongo.org."
            )
        if self.user_instance:
            self.fields["username"].initial = self.user_instance.username
            self.fields["first_name"].initial = self.user_instance.first_name
            self.fields["last_name"].initial = self.user_instance.last_name
            self.fields["email"].initial = self.user_instance.email
            self.fields["is_active"].initial = self.user_instance.is_active
        if self.profile_instance:
            self.fields["role"].initial = self.profile_instance.role
            self.fields["telephone"].initial = self.profile_instance.telephone
            self.fields["mpesa_numero"].initial = self.profile_instance.mpesa_numero
            self.fields["date_embauche"].initial = self.profile_instance.date_embauche
            self.fields["date_naissance"].initial = self.profile_instance.date_naissance
            self.fields["salaire_mensuel_usd"].initial = self.profile_instance.salaire_mensuel_usd

    def clean_username(self):
        username = self.cleaned_data["username"]
        query = User.objects.filter(username=username)
        if self.user_instance:
            query = query.exclude(id=self.user_instance.id)
        if query.exists():
            raise forms.ValidationError("Cet identifiant est déjà utilisé.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email", "")
        if not email:
            return email
        query = User.objects.filter(email=email)
        if self.user_instance:
            query = query.exclude(id=self.user_instance.id)
        if query.exists():
            raise forms.ValidationError("Cet email est déjà utilisé.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if not self.user_instance and not password:
            raise forms.ValidationError("Le mot de passe est obligatoire à la création.")
        return password

    def clean_cv_file(self):
        cv_file = self.cleaned_data.get("cv_file")
        if not cv_file:
            return cv_file
        return _validate_uploaded_cv_file(cv_file)

    def clean_role(self):
        role = self.cleaned_data["role"]
        allowed_roles = {UserProfile.EMPLOYEE_ROLE, UserProfile.CAMERA_CONTROLLER_ROLE}
        if role not in allowed_roles:
            raise forms.ValidationError("Choisissez un rôle valide pour ce compte.")
        return role

    def clean(self):
        cleaned_data = super().clean()
        cv_file = cleaned_data.get("cv_file")
        reviewed_cv_source = (cleaned_data.get("reviewed_cv_source") or "").strip()

        if cv_file and reviewed_cv_source:
            raise forms.ValidationError(
                "Choisissez soit un fichier CV local, soit un CV déjà enregistré sur shinecongo.org, mais pas les deux."
            )

        if reviewed_cv_source:
            selected_candidate = self.reviewed_candidate_choices_by_id.get(reviewed_cv_source)
            if not selected_candidate:
                raise forms.ValidationError("Le CV sélectionné n'est plus disponible. Rechargez la page puis réessayez.")
            if selected_candidate.cv_url:
                cleaned_data["resolved_cv_file"] = _download_cv_from_url(
                    selected_candidate.cv_url,
                    "Le CV sélectionné doit provenir de shinecongo.org.",
                )
            else:
                cleaned_data["resolved_cv_file"] = build_candidate_dossier_pdf(selected_candidate)

        return cleaned_data

    def save(self, site):
        if self.user_instance:
            user = self.user_instance
        else:
            user = User()

        user.username = self.cleaned_data["username"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data.get("email", "")
        user.is_active = self.cleaned_data.get("is_active", True)

        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        elif not user.pk:
            user.set_unusable_password()

        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = self.cleaned_data["role"]
        profile.site = site
        profile.telephone = self.cleaned_data.get("telephone", "")
        profile.mpesa_numero = self.cleaned_data.get("mpesa_numero", "")
        profile.date_embauche = self.cleaned_data.get("date_embauche")
        profile.date_naissance = self.cleaned_data.get("date_naissance")
        profile.salaire_mensuel_usd = self.cleaned_data.get("salaire_mensuel_usd")
        if password:
            profile.password_reference = password
        resolved_cv_file = self.cleaned_data.get("resolved_cv_file") or self.cleaned_data.get("cv_file")
        if resolved_cv_file:
            if profile.cv_file:
                profile.cv_file.delete(save=False)
            profile.cv_file = resolved_cv_file
        profile_photo = self.cleaned_data.get("profile_photo")
        if profile_photo:
            profile.profile_photo = profile_photo
        profile.actif = user.is_active
        profile.save()
        return profile


class AdminReminderForm(forms.ModelForm):
    due_at = forms.DateTimeField(
        label="Échéance",
        required=False,
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        help_text="Optionnel. Heure de Kinshasa recommandée pour les rappels sensibles.",
    )

    class Meta:
        model = AdminReminder
        fields = ["target", "priority", "title", "description", "due_at"]
        widgets = {
            "target": forms.Select(attrs={"class": "form-control"}),
            "priority": forms.Select(attrs={"class": "form-control"}),
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex: Préparer le contenu de shinecongo.org",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Détail du rappel ou de la notification.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.due_at:
            self.initial["due_at"] = timezone.localtime(self.instance.due_at).strftime("%Y-%m-%dT%H:%M")

    def clean_due_at(self):
        due_at = self.cleaned_data.get("due_at")
        if due_at and timezone.is_naive(due_at):
            due_at = timezone.make_aware(due_at, timezone.get_current_timezone())
        return due_at


class AdminPasswordManagementForm(forms.Form):
    """
    Formulaire simple pour permettre à un admin de redéfinir un mot de passe.
    """

    new_password1 = forms.CharField(
        label="Nouveau mot de passe",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Nouveau mot de passe",
                "autocomplete": "new-password",
                "minlength": "4",
            }
        ),
        help_text="Minimum 4 caractères.",
    )
    new_password2 = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Confirmez le mot de passe",
                "autocomplete": "new-password",
                "minlength": "4",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("new_password1")
        password2 = cleaned_data.get("new_password2")

        if password1 and len(password1) < 4:
            self.add_error("new_password1", "Le mot de passe doit contenir au moins 4 caractères.")

        if password1 and password2 and password1 != password2:
            self.add_error("new_password2", "Les mots de passe ne correspondent pas.")

        return cleaned_data

    def save(self, user):
        user.set_password(self.cleaned_data["new_password1"])
        user.save(update_fields=["password"])
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.set_password_reference(self.cleaned_data["new_password1"])
        return user


class AdminPasswordReferenceForm(forms.Form):
    """
    Formulaire admin pour mémoriser visiblement un mot de passe sans le changer réellement.
    """

    password_reference = forms.CharField(
        label="Mot de passe visible",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Saisissez le mot de passe à mémoriser",
                "autocomplete": "off",
            }
        ),
        help_text="Ce mémo ne change pas le vrai mot de passe du compte.",
    )

    def clean_password_reference(self):
        return (self.cleaned_data.get("password_reference") or "").strip()


class EmployeePaymentForm(forms.Form):
    """
    Enregistrer un paiement employé et générer la fiche de paiement.
    """

    payment_date = forms.DateField(
        label="Date de paiement",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    period_start = forms.DateField(
        label="Période du",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    period_end = forms.DateField(
        label="Période au",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    amount_paid_usd = forms.DecimalField(
        label="Montant payé (USD)",
        min_value=0,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    payment_method = forms.ChoiceField(
        label="Mode de paiement",
        choices=EmployeePayment.PAYMENT_METHOD_CHOICES,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    mpesa_reference = forms.CharField(
        label="Référence M-Pesa",
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    employee_signature_name = forms.CharField(
        label="Signature employé (nom complet)",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    notes = forms.CharField(
        label="Notes",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def __init__(self, *args, employee_profile=None, **kwargs):
        self.employee_profile = employee_profile
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        month_start = today.replace(day=1)
        self.fields["payment_date"].initial = today
        self.fields["period_start"].initial = month_start
        self.fields["period_end"].initial = today
        salaire = getattr(employee_profile, "salaire_mensuel_usd", None)
        if salaire is not None:
            self.fields["amount_paid_usd"].initial = salaire

    def clean(self):
        cleaned_data = super().clean()
        period_start = cleaned_data.get("period_start")
        period_end = cleaned_data.get("period_end")
        payment_method = cleaned_data.get("payment_method")
        mpesa_reference = cleaned_data.get("mpesa_reference", "").strip()

        if period_start and period_end and period_start > period_end:
            raise forms.ValidationError("La date de début de période doit être antérieure à la date de fin.")

        if payment_method == "MPESA" and not mpesa_reference:
            raise forms.ValidationError("La référence M-Pesa est obligatoire pour un paiement M-Pesa.")

        return cleaned_data


class SiteJournalEntryForm(forms.ModelForm):
    amount_usd = forms.DecimalField(
        label="Montant lié (USD)",
        required=False,
        min_value=Decimal("0"),
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
    )
    reminder_at = forms.DateTimeField(
        label="Rappel par email",
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            attrs={"class": "form-control", "type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
    )

    def __init__(self, *args, reminder_user=None, **kwargs):
        self.reminder_user = reminder_user
        super().__init__(*args, **kwargs)
        self.default_reminder_email = self._resolve_reminder_email()
        rate_data = get_usd_to_cdf_rate()
        self.usd_to_cdf_rate = Decimal(str(rate_data.get("usd_to_cdf") or "0"))
        if self.usd_to_cdf_rate <= 0:
            self.usd_to_cdf_rate = Decimal("1")
        self.fx_rate_label = f"1 USD = {self.usd_to_cdf_rate.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,.0f} FC".replace(",", " ")

        if self.instance and self.instance.pk and self.instance.reminder_at:
            self.initial["reminder_at"] = timezone.localtime(self.instance.reminder_at).strftime("%Y-%m-%dT%H:%M")
        if self.instance and self.instance.pk and self.instance.amount_fc:
            conversion = convert_cdf_to_usd(self.instance.amount_fc)
            self.initial["amount_usd"] = conversion["amount_usd"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if self.default_reminder_email:
            self.fields["reminder_at"].help_text = (
                f"Optionnel. Si vous choisissez une date et une heure, un email sera envoyé à "
                f"{self.default_reminder_email} (heure de Kinshasa)."
            )
        else:
            self.fields["reminder_at"].help_text = (
                "Optionnel. Ajoutez un email à votre compte administrateur pour recevoir ce rappel."
            )

        amount_help_text = (
            "Optionnel. Entrez le montant en FC ou en USD. Le portail convertit automatiquement avec le taux du jour "
            f"({self.fx_rate_label})."
        )
        self.fields["amount_fc"].help_text = amount_help_text
        self.fields["amount_usd"].help_text = amount_help_text
        self.fields["amount_fc"].widget.attrs["data-journal-fx"] = "fc"
        self.fields["amount_usd"].widget.attrs["data-journal-fx"] = "usd"

    def _resolve_reminder_email(self):
        candidates = [
            getattr(self.reminder_user, "email", ""),
            getattr(self.instance, "reminder_email", ""),
            getattr(settings, "FINAL_REPORT_NOTIFICATION_EMAIL", ""),
            getattr(settings, "EMAIL_HOST_USER", ""),
        ]
        for value in candidates:
            email = str(value or "").strip()
            if email:
                return email
        return ""

    class Meta:
        model = SiteJournalEntry
        fields = ["entry_date", "category", "title", "description", "amount_fc", "reminder_at"]
        widgets = {
            "entry_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "category": forms.Select(attrs={"class": "form-control"}),
            "title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex: Achat matériel, visite du site, décision à retenir"}
            ),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 4, "placeholder": "Décrivez ce qui a été fait, constaté ou payé"}
            ),
            "amount_fc": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
        }
        help_texts = {
            "amount_fc": "Optionnel. Ce montant reste informatif et n'entre pas automatiquement dans les calculs financiers.",
        }

    def clean_reminder_at(self):
        reminder_at = self.cleaned_data.get("reminder_at")
        if reminder_at and timezone.is_naive(reminder_at):
            reminder_at = timezone.make_aware(reminder_at, timezone.get_current_timezone())
        return reminder_at

    def clean(self):
        cleaned_data = super().clean()
        amount_fc = cleaned_data.get("amount_fc")
        amount_usd = cleaned_data.get("amount_usd")
        reminder_at = cleaned_data.get("reminder_at")

        if amount_fc is None and amount_usd is not None:
            cleaned_data["amount_fc"] = (amount_usd * self.usd_to_cdf_rate).quantize(Decimal("0.01"))
        elif amount_fc is not None:
            cleaned_data["amount_usd"] = (amount_fc / self.usd_to_cdf_rate).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

        if not reminder_at:
            return cleaned_data

        if not self._resolve_reminder_email():
            self.add_error(
                "reminder_at",
                "Ajoutez un email valide à votre compte administrateur pour programmer un rappel.",
            )
            return cleaned_data

        reminder_is_already_sent = bool(
            self.instance
            and self.instance.pk
            and self.instance.reminder_sent_at
            and self.instance.reminder_at == reminder_at
        )

        if reminder_at <= timezone.now() and not reminder_is_already_sent:
            self.add_error(
                "reminder_at",
                "Choisissez une date et une heure futures (heure de Kinshasa).",
            )

        return cleaned_data

    def save(self, commit=True):
        entry = super().save(commit=False)
        reminder_email = self._resolve_reminder_email()
        previous_reminder_at = self.instance.reminder_at if self.instance and self.instance.pk else None
        previous_reminder_email = self.instance.reminder_email if self.instance and self.instance.pk else ""

        if entry.reminder_at:
            entry.reminder_email = reminder_email
            if previous_reminder_at != entry.reminder_at or previous_reminder_email != entry.reminder_email:
                entry.reminder_sent_at = None
        else:
            entry.reminder_email = ""
            entry.reminder_sent_at = None

        if commit:
            entry.save()

        return entry


class SiteJournalEntryMoveForm(forms.Form):
    """
    Formulaire dédié à la migration d'une entrée du journal vers une autre catégorie/date.
    """

    entry_date = forms.DateField(
        label="Nouvelle date",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    category = forms.ChoiceField(
        label="Nouvelle catégorie",
        choices=SiteJournalEntry.CATEGORY_CHOICES,
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, entry_instance=None, **kwargs):
        self.entry_instance = entry_instance
        super().__init__(*args, **kwargs)

        if self.entry_instance:
            self.fields["entry_date"].initial = self.entry_instance.entry_date
            self.fields["category"].initial = self.entry_instance.category

    def save(self, entry):
        entry.entry_date = self.cleaned_data["entry_date"]
        entry.category = self.cleaned_data["category"]
        entry.save(update_fields=["entry_date", "category", "updated_at"])
        return entry


class SiteDocumentMoveForm(forms.Form):
    """
    Formulaire dédié à la migration d'un document vers une autre section documentaire.
    """

    file_type = forms.ChoiceField(
        label="Nouvelle section",
        choices=SiteDocument.FILE_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, document_instance=None, **kwargs):
        self.document_instance = document_instance
        super().__init__(*args, **kwargs)

        if self.document_instance and not self.is_bound:
            self.fields["file_type"].initial = self.document_instance.file_type

    def save(self, document):
        document.file_type = self.cleaned_data["file_type"]
        document.save(update_fields=["file_type", "updated_at"])
        return document


class SiteWaterPurchaseMoveForm(forms.Form):
    ASSIGNMENT_SCOPE_CHOICES = [
        ("GENERAL", "General du mois"),
        ("WEEK", "Affecter a une semaine"),
    ]

    billing_month = forms.DateField(
        label="Nouveau mois concerne",
        input_formats=["%Y-%m"],
        widget=forms.DateInput(
            format="%Y-%m",
            attrs={"class": "form-control", "type": "month"},
        ),
    )
    assignment_scope = forms.ChoiceField(
        label="Imputation dans le mois",
        choices=ASSIGNMENT_SCOPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-control"}),
        help_text="Choisissez General du mois pour sortir cet achat du detail hebdomadaire, ou une semaine precise pour le rattacher a un bloc hebdomadaire.",
    )
    reporting_week_date = forms.DateField(
        label="Jour de la semaine cible",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        help_text="Choisissez n'importe quel jour de la semaine cible dans le mois concerne.",
    )

    def __init__(self, *args, purchase_instance=None, **kwargs):
        self.purchase_instance = purchase_instance
        super().__init__(*args, **kwargs)

        if self.purchase_instance and not self.is_bound:
            effective_reporting_date = self.purchase_instance.get_reporting_week_date()
            self.fields["billing_month"].initial = self.purchase_instance.billing_month
            self.fields["assignment_scope"].initial = "WEEK" if effective_reporting_date else "GENERAL"
            self.fields["reporting_week_date"].initial = effective_reporting_date

    def clean_billing_month(self):
        billing_month = self.cleaned_data["billing_month"]
        return billing_month.replace(day=1)

    def clean(self):
        cleaned_data = super().clean()
        billing_month = cleaned_data.get("billing_month")
        assignment_scope = cleaned_data.get("assignment_scope")
        reporting_week_date = cleaned_data.get("reporting_week_date")

        if assignment_scope == "WEEK":
            if not reporting_week_date:
                self.add_error(
                    "reporting_week_date",
                    "Choisissez un jour dans la semaine cible pour rattacher cet achat.",
                )
            elif (
                billing_month
                and (
                    reporting_week_date.year != billing_month.year
                    or reporting_week_date.month != billing_month.month
                )
            ):
                self.add_error(
                    "reporting_week_date",
                    "La semaine choisie doit appartenir au mois concerne.",
                )
        else:
            cleaned_data["reporting_week_date"] = None

        return cleaned_data

    def save(self, purchase):
        purchase.billing_month = self.cleaned_data["billing_month"]
        purchase.reporting_week_date = self.cleaned_data.get("reporting_week_date")
        purchase.save(update_fields=["billing_month", "reporting_week_date", "updated_at"])
        return purchase


class WaterSupplierForm(forms.ModelForm):
    class Meta:
        model = WaterSupplier
        fields = ["name", "price_per_tank_fc", "is_default", "is_active", "notes"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex: Forage Kintambo"}
            ),
            "price_per_tank_fc": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
            "is_default": forms.CheckboxInput(),
            "is_active": forms.CheckboxInput(),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optionnel: zone desservie, contact, consignes de paiement...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.is_bound:
            self.fields["is_active"].initial = True

    def clean(self):
        cleaned_data = super().clean()
        is_active = cleaned_data.get("is_active")
        other_active_suppliers = WaterSupplier.objects.exclude(pk=self.instance.pk).filter(is_active=True)

        if is_active is False and not other_active_suppliers.exists():
            self.add_error(
                "is_active",
                "Gardez au moins un fournisseur actif pour continuer à enregistrer les achats d'eau.",
            )

        return cleaned_data


class SiteWaterPurchaseForm(forms.ModelForm):
    billing_month = forms.DateField(
        label="Mois concerné",
        help_text="Sélectionnez le mois auquel cet achat d'eau doit être rattaché.",
        input_formats=["%Y-%m"],
        widget=forms.DateInput(
            format="%Y-%m",
            attrs={"class": "form-control", "type": "month"},
        ),
    )

    class Meta:
        model = SiteWaterPurchase
        fields = ["site", "supplier", "billing_month", "purchase_date", "amount_fc", "notes"]
        widgets = {
            "site": forms.Select(attrs={"class": "form-control"}),
            "supplier": forms.Select(attrs={"class": "form-control"}),
            "purchase_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "amount_fc": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "notes": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "placeholder": "Optionnel: remarque sur le remplissage ou le transport"}
            ),
        }
        help_texts = {
            "amount_fc": "",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_month = timezone.localdate().replace(day=1)
        selected_month = self._resolve_selected_month(current_month)
        default_supplier = get_water_purchase_default_supplier()
        supplier_queryset = WaterSupplier.objects.filter(is_active=True)
        if self.instance and self.instance.pk and self.instance.supplier_id:
            supplier_queryset = WaterSupplier.objects.filter(
                Q(is_active=True) | Q(pk=self.instance.supplier_id)
            )
        supplier_queryset = supplier_queryset.order_by("-is_default", "name")
        self.fields["site"].queryset = Location.objects.filter(actif=True).order_by("nom")
        self.fields["supplier"].queryset = supplier_queryset
        self.fields["supplier"].required = False
        selected_supplier = self._resolve_selected_supplier(default_supplier)
        if not self.is_bound:
            self.fields["billing_month"].initial = selected_month
            self.fields["purchase_date"].initial = self.initial.get("purchase_date") or timezone.localdate()
            self.fields["supplier"].initial = (
                self.instance.supplier if self.instance and self.instance.pk else selected_supplier
            )
            if self.instance and self.instance.pk:
                self.fields["amount_fc"].initial = self.instance.amount_fc
            else:
                self.fields["amount_fc"].initial = get_water_purchase_default_amount(
                    selected_month,
                    supplier=selected_supplier,
                )

        self.fields["amount_fc"].help_text = get_water_purchase_amount_help_text(
            selected_month,
            supplier=selected_supplier,
        )

        if self.instance and self.instance.pk and self.instance.billing_month:
            self.initial["billing_month"] = self.instance.billing_month
        if self.instance and self.instance.pk and self.instance.supplier_id:
            self.initial["supplier"] = self.instance.supplier

    def clean_billing_month(self):
        billing_month = self.cleaned_data["billing_month"]
        return billing_month.replace(day=1)

    def clean_supplier(self):
        supplier = self.cleaned_data.get("supplier")
        return supplier or get_water_purchase_default_supplier()

    def _resolve_selected_month(self, fallback_month):
        if self.instance and self.instance.pk and self.instance.billing_month:
            return self.instance.billing_month.replace(day=1)

        raw_month = self.data.get("billing_month") if self.is_bound else self.initial.get("billing_month")
        if hasattr(raw_month, "replace") and not isinstance(raw_month, str):
            return raw_month.replace(day=1)
        if isinstance(raw_month, str) and raw_month:
            try:
                return datetime.strptime(raw_month, "%Y-%m").date().replace(day=1)
            except ValueError:
                try:
                    return datetime.strptime(raw_month, "%Y-%m-%d").date().replace(day=1)
                except ValueError:
                    return fallback_month
        return fallback_month

    def _resolve_selected_supplier(self, fallback_supplier):
        if self.instance and self.instance.pk and self.instance.supplier_id:
            return self.instance.supplier

        raw_supplier = self.data.get("supplier") if self.is_bound else self.initial.get("supplier")
        resolved_supplier = _resolve_water_supplier(raw_supplier)
        return resolved_supplier or fallback_supplier


class CameraForm(forms.ModelForm):
    class Meta:
        model = Camera
        fields = [
            "name",
            "camera_number",
            "camera_position",
            "app_name",
            "notes",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Caméra entrée principale"}),
            "camera_number": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "camera_position": forms.Select(attrs={"class": "form-control"}),
            "app_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: V380, Hik-Connect..."}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Remarques d'installation, angle, accès..."}),
            "is_active": forms.CheckboxInput(),
        }


class DailyCameraReportForm(forms.ModelForm):
    class Meta:
        model = DailyCameraReport
        fields = [
            "date",
            "cars_count",
            "motos_count",
            "three_wheelers_count",
            "notes",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "cars_count": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "motos_count": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "three_wheelers_count": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Notes sur le comptage, le trafic, une anomalie ou une précision terrain.",
                }
            ),
        }
        help_texts = {
            "cars_count": "Prix voiture: 15 000 FC",
            "motos_count": "Prix moto (2 pneus): 3 000 FC",
            "three_wheelers_count": "Prix moto à 3 pneus: 5 000 FC",
        }


class VideoEvidenceForm(forms.ModelForm):
    class Meta:
        model = VideoEvidence
        fields = [
            "camera",
            "title",
            "evidence_type",
            "clip_date",
            "start_time",
            "end_time",
            "uploaded_file",
            "notes",
        ]
        widgets = {
            "camera": forms.Select(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Clip entrée 08h15"}),
            "evidence_type": forms.Select(attrs={"class": "form-control"}),
            "clip_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "start_time": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "end_time": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "uploaded_file": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": "video/*,image/*,.mp4,.mov,.avi,.mkv,.webm,.jpg,.jpeg,.png,.webp",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Expliquez pourquoi ce clip ou cette capture doit être conservé.",
                }
            ),
        }

    def __init__(self, *args, site=None, daily_report=None, **kwargs):
        self.site = site or getattr(daily_report, "site", None)
        self.daily_report = daily_report
        super().__init__(*args, **kwargs)

        if self.site:
            self.fields["camera"].queryset = Camera.objects.filter(site=self.site).order_by("camera_number", "name")
        else:
            self.fields["camera"].queryset = Camera.objects.none()

        if self.daily_report and not self.is_bound:
            self.fields["clip_date"].initial = self.daily_report.date

    def clean(self):
        cleaned_data = super().clean()
        camera = cleaned_data.get("camera")
        if camera and self.site and camera.site_id != self.site.id:
            self.add_error("camera", "Choisissez une caméra du site concerné.")
        return cleaned_data
