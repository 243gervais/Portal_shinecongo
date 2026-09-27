from django import forms
from django.contrib.auth.models import User

from .models import (
    Contract,
    CorporateCompany,
    CorporateContact,
    RecurringSchedule,
    Vehicle,
    WorkOrder,
    WorkOrderProofPhoto,
    WorkOrderVehicle,
)


FORM_CLASS = "form-control"


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css_class} {FORM_CLASS}".strip()


class CorporateCompanyForm(StyledModelForm):
    class Meta:
        model = CorporateCompany
        fields = [
            "legal_name",
            "trading_name",
            "address",
            "commune",
            "city",
            "rccm",
            "tax_number",
            "id_nat",
            "billing_email",
            "telephone",
            "default_payment_terms_days",
            "is_active",
            "internal_notes",
        ]
        widgets = {"internal_notes": forms.Textarea(attrs={"rows": 3}), "address": forms.Textarea(attrs={"rows": 3})}


class CorporateContactForm(StyledModelForm):
    class Meta:
        model = CorporateContact
        fields = ["company", "role", "full_name", "title", "telephone", "email", "is_active", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class ContractForm(StyledModelForm):
    class Meta:
        model = Contract
        fields = [
            "contract_number",
            "company",
            "title",
            "start_date",
            "end_date",
            "status",
            "billing_frequency",
            "currency",
            "monthly_package_price",
            "included_washes_per_month",
            "included_visits_per_month",
            "additional_wash_price",
            "minimum_vehicles_per_intervention",
            "minimum_intervention_charge",
            "payment_terms_days",
            "service_location",
            "default_service_type",
            "default_team_size",
            "client_obligations",
            "shine_obligations",
            "cancellation_notice",
            "notes",
            "signed_contract_file",
            "signed_date",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "signed_date": forms.DateInput(attrs={"type": "date"}),
            "service_location": forms.Textarea(attrs={"rows": 3}),
            "client_obligations": forms.Textarea(attrs={"rows": 3}),
            "shine_obligations": forms.Textarea(attrs={"rows": 3}),
            "cancellation_notice": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class VehicleForm(StyledModelForm):
    class Meta:
        model = Vehicle
        fields = [
            "company",
            "internal_fleet_number",
            "license_plate",
            "vehicle_type",
            "make",
            "model",
            "color",
            "year",
            "notes",
            "is_active",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class RecurringScheduleForm(StyledModelForm):
    class Meta:
        model = RecurringSchedule
        fields = [
            "contract",
            "company",
            "service_location",
            "weekday",
            "planned_start_time",
            "planned_duration_minutes",
            "planned_vehicles",
            "default_assigned_team",
            "start_date",
            "end_date",
            "is_active",
            "instructions",
        ]
        widgets = {
            "planned_start_time": forms.TimeInput(attrs={"type": "time"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "default_assigned_team": forms.CheckboxSelectMultiple,
            "service_location": forms.Textarea(attrs={"rows": 3}),
            "instructions": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_assigned_team"].queryset = User.objects.filter(is_active=True).order_by("first_name", "username")


class WorkOrderManagerForm(StyledModelForm):
    class Meta:
        model = WorkOrder
        fields = [
            "contract",
            "company",
            "schedule",
            "service_location",
            "scheduled_start",
            "planned_duration_minutes",
            "assigned_employees",
            "team_leader",
            "planned_vehicles",
            "price_classification",
            "status",
            "review_notes",
        ]
        widgets = {
            "scheduled_start": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "assigned_employees": forms.CheckboxSelectMultiple,
            "service_location": forms.Textarea(attrs={"rows": 3}),
            "review_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        users = User.objects.filter(is_active=True).order_by("first_name", "username")
        self.fields["assigned_employees"].queryset = users
        self.fields["team_leader"].queryset = users


class WorkOrderFieldForm(StyledModelForm):
    class Meta:
        model = WorkOrder
        fields = [
            "actual_arrival",
            "actual_departure",
            "associate_name",
            "associate_signature",
            "client_representative_name",
            "client_signature",
            "observations",
            "machine_fuel_litres",
            "machine_fuel_amount",
            "soap_cost",
            "perfume_cost",
            "water_cost",
            "other_consumables_cost",
            "transportation_cost",
            "equipment_maintenance_allocation",
        ]
        widgets = {
            "actual_arrival": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "actual_departure": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "observations": forms.Textarea(attrs={"rows": 3}),
        }


class WorkOrderVehicleForm(StyledModelForm):
    class Meta:
        model = WorkOrderVehicle
        fields = ["vehicle", "license_plate_snapshot", "service_type", "status", "billable_amount", "before_photo", "after_photo", "observations"]
        widgets = {"observations": forms.Textarea(attrs={"rows": 2})}


WorkOrderVehicleFormSet = forms.inlineformset_factory(
    WorkOrder,
    WorkOrderVehicle,
    form=WorkOrderVehicleForm,
    extra=1,
    can_delete=True,
)


class WorkOrderProofPhotoForm(StyledModelForm):
    class Meta:
        model = WorkOrderProofPhoto
        fields = ["photo", "photo_type"]


class GenerateScheduleForm(forms.Form):
    date_from = forms.DateField(label="Debut", widget=forms.DateInput(attrs={"type": "date", "class": FORM_CLASS}))
    date_to = forms.DateField(label="Fin", widget=forms.DateInput(attrs={"type": "date", "class": FORM_CLASS}))

    def clean(self):
        cleaned = super().clean()
        date_from = cleaned.get("date_from")
        date_to = cleaned.get("date_to")
        if date_from and date_to and date_to < date_from:
            raise forms.ValidationError("La date de fin doit etre apres la date de debut.")
        return cleaned

