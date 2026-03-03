from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from sites.models import Location


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
    site_nom = forms.CharField(
        label="Nom du site",
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: Station Texaco Gombe'
        }),
        help_text="Nom du site/location où vous travaillez"
    )
    site_adresse = forms.CharField(
        label="Adresse du site",
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Adresse complète du site (optionnel)'
        })
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
            
            # Créer ou récupérer le site
            site_nom = self.cleaned_data.get('site_nom')
            site_adresse = self.cleaned_data.get('site_adresse', '')
            
            # Vérifier si un site avec ce nom existe déjà
            site, created = Location.objects.get_or_create(
                nom=site_nom,
                defaults={
                    'adresse': site_adresse,
                    'actif': True
                }
            )
            
            profile.site = site
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
