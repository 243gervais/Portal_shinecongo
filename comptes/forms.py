from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from shinecongo.currency import convert_cdf_to_usd, get_usd_to_cdf_rate
from sites.models import Camera, DailyCameraReport, Location, SiteJournalEntry, SiteWaterPurchase, VideoEvidence

from .models import AdminReminder, EmployeePayment, UserProfile


WATER_RATE_CHANGE_MONTH = date(2026, 5, 1)
WATER_DEFAULT_AMOUNT_BEFORE_CHANGE = Decimal("24000")
WATER_DEFAULT_AMOUNT_AFTER_CHANGE = Decimal("22000")


def get_water_purchase_default_amount(target_month=None):
    if target_month is None:
        target_month = timezone.localdate()
    month_start = target_month.replace(day=1)
    if month_start >= WATER_RATE_CHANGE_MONTH:
        return WATER_DEFAULT_AMOUNT_AFTER_CHANGE
    return WATER_DEFAULT_AMOUNT_BEFORE_CHANGE


def get_water_purchase_amount_help_text(target_month=None):
    month_start = (target_month or timezone.localdate()).replace(day=1)
    suggested_amount = get_water_purchase_default_amount(month_start)
    if month_start >= WATER_RATE_CHANGE_MONTH:
        return (
            f"Montant suggéré pour ce mois : {suggested_amount:,.0f} FC. "
            "Depuis le 01/05/2026, le tarif d'eau est passé de 24 000 FC à 22 000 FC. "
            "Vous pouvez toujours le modifier si nécessaire."
        ).replace(",", " ")
    return (
        f"Montant suggéré pour ce mois : {suggested_amount:,.0f} FC. "
        "À partir du 01/05/2026, le tarif conseillé passera à 22 000 FC. "
        "Vous pouvez toujours le modifier si nécessaire."
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
    Création / mise à jour d'un employé rattaché à un site.
    """

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

    def __init__(self, *args, user_instance=None, profile_instance=None, **kwargs):
        self.user_instance = user_instance
        self.profile_instance = profile_instance
        super().__init__(*args, **kwargs)

        if self.user_instance:
            self.fields["username"].initial = self.user_instance.username
            self.fields["first_name"].initial = self.user_instance.first_name
            self.fields["last_name"].initial = self.user_instance.last_name
            self.fields["email"].initial = self.user_instance.email
            self.fields["is_active"].initial = self.user_instance.is_active
        if self.profile_instance:
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
        profile.role = "EMPLOYE"
        profile.site = site
        profile.telephone = self.cleaned_data.get("telephone", "")
        profile.mpesa_numero = self.cleaned_data.get("mpesa_numero", "")
        profile.date_embauche = self.cleaned_data.get("date_embauche")
        profile.date_naissance = self.cleaned_data.get("date_naissance")
        profile.salaire_mensuel_usd = self.cleaned_data.get("salaire_mensuel_usd")
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
        return user


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
        fields = ["site", "billing_month", "purchase_date", "amount_fc", "notes"]
        widgets = {
            "site": forms.Select(attrs={"class": "form-control"}),
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
        self.fields["site"].queryset = Location.objects.filter(actif=True).order_by("nom")
        if not self.is_bound:
            self.fields["billing_month"].initial = selected_month
            self.fields["purchase_date"].initial = self.initial.get("purchase_date") or timezone.localdate()
            if self.instance and self.instance.pk:
                self.fields["amount_fc"].initial = self.instance.amount_fc
            else:
                self.fields["amount_fc"].initial = get_water_purchase_default_amount(selected_month)

        self.fields["amount_fc"].help_text = get_water_purchase_amount_help_text(selected_month)

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
            "notes",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "cars_count": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "motos_count": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
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
            "motos_count": "Prix moto: 10 000 FC",
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
