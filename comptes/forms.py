from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.utils import timezone
from sites.models import Location
from .models import UserProfile, EmployeePayment


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
    salaire_mensuel_fc = forms.DecimalField(
        label="Salaire mensuel (FC)",
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=12,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
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
            self.fields["salaire_mensuel_fc"].initial = self.profile_instance.salaire_mensuel_fc

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
        profile.salaire_mensuel_fc = self.cleaned_data.get("salaire_mensuel_fc")
        profile.actif = user.is_active
        profile.save()
        return profile


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
    amount_paid_fc = forms.DecimalField(
        label="Montant payé (FC)",
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
        salaire = getattr(employee_profile, "salaire_mensuel_fc", None)
        if salaire is not None:
            self.fields["amount_paid_fc"].initial = salaire

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
