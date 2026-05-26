from django import forms

from .models import Camera, CameraObservation, CameraOperatorDailyReport


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleImageInput

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data]
        if not data:
            return []
        return [single_clean(data, initial)]


class CameraObservationForm(forms.Form):
    camera = forms.ModelChoiceField(
        queryset=Camera.objects.none(),
        label="Caméra",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    vehicle_type = forms.ChoiceField(
        label="Type de véhicule",
        choices=CameraObservation.VEHICLE_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    observed_time = forms.TimeField(
        label="Heure observée",
        required=False,
        widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
    )
    screenshots = MultipleImageField(
        label="Captures du véhicule",
        required=True,
        help_text="Ajoutez une ou plusieurs captures pour ce véhicule.",
        widget=MultipleImageInput(
            attrs={
                "class": "form-control",
                "accept": ".jpg,.jpeg,.png,.webp,.gif,image/jpeg,image/png,image/webp,image/gif",
                "multiple": True,
            }
        ),
    )
    time_proof = forms.ImageField(
        label="Preuve horaire (optionnel)",
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".jpg,.jpeg,.png,.webp,.gif,image/jpeg,image/png,image/webp,image/gif",
            }
        ),
    )
    notes = forms.CharField(
        label="Notes",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Optionnel: angle caméra, doute sur la plaque, précision utile pour l'admin...",
            }
        ),
    )

    def __init__(self, *args, site=None, **kwargs):
        self.site = site
        super().__init__(*args, **kwargs)
        if self.site:
            self.fields["camera"].queryset = Camera.objects.filter(site=self.site, is_active=True).order_by(
                "camera_number", "name"
            )

    def clean_camera(self):
        camera = self.cleaned_data["camera"]
        if self.site and camera.site_id != self.site.id:
            raise forms.ValidationError("Choisissez une caméra du site concerné.")
        return camera

    def clean_screenshots(self):
        screenshots = self.cleaned_data.get("screenshots") or []
        if not screenshots:
            raise forms.ValidationError("Ajoutez au moins une capture pour enregistrer cette observation.")
        return screenshots


class CameraOperatorDailyReportFinalForm(forms.ModelForm):
    class Meta:
        model = CameraOperatorDailyReport
        fields = ["notes"]
        widgets = {
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Résumé de fin de journée, anomalies, volume inhabituel, angle mort, etc.",
                }
            ),
        }
