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
    plate_number = forms.CharField(
        label="Plaque",
        required=False,
        max_length=30,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Optionnel: AB1234, 123CD...",
            }
        ),
    )
    observed_time = forms.TimeField(
        label="Heure observée",
        required=False,
        widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
    )
    screenshots = MultipleImageField(
        label="Captures du véhicule",
        required=False,
        help_text="Optionnel. Ajoutez une ou plusieurs captures si vous en avez besoin.",
        widget=MultipleImageInput(
            attrs={
                "class": "form-control",
                "accept": ".jpg,.jpeg,.png,.webp,.gif,image/jpeg,image/png,image/webp,image/gif",
                "multiple": True,
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
        return self.cleaned_data.get("screenshots") or []

    def clean_plate_number(self):
        plate_number = (self.cleaned_data.get("plate_number") or "").strip().upper()
        return plate_number


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
