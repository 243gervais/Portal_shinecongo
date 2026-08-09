from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from lavages.models import CarWash, CarWashPhoto
from pointage.models import ShiftDay
from problemes.models import IssueReport
from sites.models import Location, SiteFuelPurchase, SiteWaterPurchase


def _absolute_media_url(request, file_field):
    if not file_field:
        return ""
    try:
        url = file_field.url
    except ValueError:
        return ""
    return request.build_absolute_uri(url) if request else url


class SiteSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ["id", "nom", "ville", "gps_actif", "rayon_autorisé_mètres"]


class CarWashPhotoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    type_photo_display = serializers.CharField(source="get_type_photo_display", read_only=True)
    filename = serializers.SerializerMethodField()

    class Meta:
        model = CarWashPhoto
        fields = [
            "id",
            "url",
            "thumbnail_url",
            "type_photo",
            "type_photo_display",
            "filename",
        ]

    def get_url(self, obj):
        return _absolute_media_url(self.context.get("request"), obj.photo)

    def get_thumbnail_url(self, obj):
        request = self.context.get("request")
        if not obj.thumbnail_url:
            return self.get_url(obj)
        return request.build_absolute_uri(obj.thumbnail_url) if request else obj.thumbnail_url

    def get_filename(self, obj):
        return obj.filename()


class EmployeeCarWashSerializer(serializers.ModelSerializer):
    type_service_display = serializers.CharField(source="get_type_service_display", read_only=True)
    date_display = serializers.SerializerMethodField()
    created_at_display = serializers.SerializerMethodField()
    photo_count = serializers.SerializerMethodField()
    plaque_photo_url = serializers.SerializerMethodField()
    plaque_photo_thumbnail_url = serializers.SerializerMethodField()
    preview_photo = serializers.SerializerMethodField()

    class Meta:
        model = CarWash
        fields = [
            "id",
            "date",
            "date_display",
            "type_service",
            "type_service_display",
            "plaque",
            "notes",
            "created_at",
            "created_at_display",
            "photo_count",
            "plaque_photo_url",
            "plaque_photo_thumbnail_url",
            "preview_photo",
        ]

    def get_date_display(self, obj):
        return obj.date.strftime("%d/%m/%Y")

    def get_created_at_display(self, obj):
        return timezone.localtime(obj.created_at).strftime("%d/%m/%Y %H:%M")

    def get_photo_count(self, obj):
        return obj.photo_count()

    def get_plaque_photo_url(self, obj):
        if not self.context.get("include_image_previews", True):
            return ""
        return _absolute_media_url(self.context.get("request"), obj.plaque_photo)

    def get_plaque_photo_thumbnail_url(self, obj):
        if not self.context.get("include_image_previews", True):
            return ""
        request = self.context.get("request")
        if not obj.plaque_photo_thumbnail_url:
            return ""
        return request.build_absolute_uri(obj.plaque_photo_thumbnail_url) if request else obj.plaque_photo_thumbnail_url

    def get_preview_photo(self, obj):
        if not self.context.get("include_image_previews", True):
            return ""
        request = self.context.get("request")
        photo = next(iter(getattr(obj, "prefetched_photos", obj.photos.all())), None)
        if not photo:
            return ""
        value = photo.thumbnail_url or photo.photo.url
        return request.build_absolute_uri(value) if request else value


class EmployeeCarWashDetailSerializer(EmployeeCarWashSerializer):
    photos = serializers.SerializerMethodField()

    class Meta(EmployeeCarWashSerializer.Meta):
        fields = EmployeeCarWashSerializer.Meta.fields + ["photos"]

    def get_photos(self, obj):
        queryset = getattr(obj, "prefetched_photos", obj.photos.all())
        return CarWashPhotoSerializer(queryset, many=True, context=self.context).data


class ManagerCarWashSerializer(EmployeeCarWashSerializer):
    employee_name = serializers.SerializerMethodField()
    site_name = serializers.CharField(source="site.nom", read_only=True)
    amount_fc = serializers.DecimalField(source="montant", max_digits=10, decimal_places=2, read_only=True)
    amount_display = serializers.SerializerMethodField()

    class Meta(EmployeeCarWashSerializer.Meta):
        fields = EmployeeCarWashSerializer.Meta.fields + [
            "employee_name",
            "site_name",
            "amount_fc",
            "amount_display",
        ]

    def get_employee_name(self, obj):
        return obj.employe.get_full_name() or obj.employe.username

    def get_amount_display(self, obj):
        return f"{Decimal(obj.montant or 0):,.0f} FC".replace(",", " ")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get("can_view_money", False):
            data.pop("amount_fc", None)
            data.pop("amount_display", None)
        return data


class EmployeeIssueSerializer(serializers.ModelSerializer):
    categorie_display = serializers.CharField(source="get_categorie_display", read_only=True)
    statut_display = serializers.CharField(source="get_statut_display", read_only=True)
    created_at_display = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    photo_thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = IssueReport
        fields = [
            "id",
            "categorie",
            "categorie_display",
            "description",
            "statut",
            "statut_display",
            "notes_resolution",
            "created_at",
            "created_at_display",
            "photo_url",
            "photo_thumbnail_url",
        ]

    def get_created_at_display(self, obj):
        return timezone.localtime(obj.created_at).strftime("%d/%m/%Y %H:%M")

    def get_photo_url(self, obj):
        return _absolute_media_url(self.context.get("request"), obj.photo)

    def get_photo_thumbnail_url(self, obj):
        request = self.context.get("request")
        if not obj.photo_thumbnail_url:
            return ""
        return request.build_absolute_uri(obj.photo_thumbnail_url) if request else obj.photo_thumbnail_url


class ManagerIssueSerializer(EmployeeIssueSerializer):
    employee_name = serializers.SerializerMethodField()
    site_name = serializers.CharField(source="site.nom", read_only=True)
    treated_by_name = serializers.SerializerMethodField()

    class Meta(EmployeeIssueSerializer.Meta):
        fields = EmployeeIssueSerializer.Meta.fields + [
            "employee_name",
            "site_name",
            "treated_by_name",
        ]

    def get_employee_name(self, obj):
        return obj.employe.get_full_name() or obj.employe.username

    def get_treated_by_name(self, obj):
        if not obj.traite_par:
            return ""
        return obj.traite_par.get_full_name() or obj.traite_par.username


class ShiftDaySerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    site_name = serializers.CharField(source="site.nom", read_only=True)
    clock_in_display = serializers.SerializerMethodField()
    clock_out_display = serializers.SerializerMethodField()
    clock_in_photo_taken_display = serializers.SerializerMethodField()
    clock_out_photo_taken_display = serializers.SerializerMethodField()
    clock_in_photo_url = serializers.SerializerMethodField()
    clock_out_photo_url = serializers.SerializerMethodField()
    clock_in_photo_thumbnail_url = serializers.SerializerMethodField()
    clock_out_photo_thumbnail_url = serializers.SerializerMethodField()
    date_display = serializers.SerializerMethodField()
    correction_by_name = serializers.SerializerMethodField()
    duration_display = serializers.SerializerMethodField()
    expenses_total_display = serializers.SerializerMethodField()
    attendance_status_code = serializers.SerializerMethodField()
    attendance_status_label = serializers.SerializerMethodField()
    attendance_status_detail = serializers.SerializerMethodField()
    clock_out_status_code = serializers.SerializerMethodField()
    clock_out_status_label = serializers.SerializerMethodField()
    clock_out_status_detail = serializers.SerializerMethodField()

    class Meta:
        model = ShiftDay
        fields = [
            "id",
            "date",
            "date_display",
            "employee_name",
            "site_name",
            "clock_in_display",
            "clock_out_display",
            "clock_in_photo_taken_display",
            "clock_out_photo_taken_display",
            "clock_in_photo_url",
            "clock_out_photo_url",
            "clock_in_photo_thumbnail_url",
            "clock_out_photo_thumbnail_url",
            "clock_in_gps_status",
            "clock_out_gps_status",
            "daily_report_confirmed",
            "total_lavages_reported",
            "total_amount_reported_fc",
            "daily_expenses_total_fc",
            "expenses_total_display",
            "attendance_status_code",
            "attendance_status_label",
            "attendance_status_detail",
            "clock_out_status_code",
            "clock_out_status_label",
            "clock_out_status_detail",
            "correction_reason",
            "corrected_at",
            "correction_by_name",
            "duration_display",
            "report_notes",
        ]

    def get_employee_name(self, obj):
        return obj.employe.get_full_name() or obj.employe.username

    def get_date_display(self, obj):
        return obj.date.strftime("%d/%m/%Y")

    def get_clock_in_display(self, obj):
        return timezone.localtime(obj.clock_in_time).strftime("%H:%M") if obj.clock_in_time else ""

    def get_clock_out_display(self, obj):
        return timezone.localtime(obj.clock_out_time).strftime("%H:%M") if obj.clock_out_time else ""

    def get_clock_in_photo_taken_display(self, obj):
        return timezone.localtime(obj.clock_in_photo_taken_at).strftime("%d/%m/%Y %H:%M") if obj.clock_in_photo_taken_at else ""

    def get_clock_out_photo_taken_display(self, obj):
        return timezone.localtime(obj.clock_out_photo_taken_at).strftime("%d/%m/%Y %H:%M") if obj.clock_out_photo_taken_at else ""

    def get_clock_in_photo_url(self, obj):
        return _absolute_media_url(self.context.get("request"), obj.clock_in_photo)

    def get_clock_out_photo_url(self, obj):
        return _absolute_media_url(self.context.get("request"), obj.clock_out_photo)

    def get_clock_in_photo_thumbnail_url(self, obj):
        request = self.context.get("request")
        if not obj.clock_in_photo_thumbnail_url:
            return ""
        return request.build_absolute_uri(obj.clock_in_photo_thumbnail_url) if request else obj.clock_in_photo_thumbnail_url

    def get_clock_out_photo_thumbnail_url(self, obj):
        request = self.context.get("request")
        if not obj.clock_out_photo_thumbnail_url:
            return ""
        return request.build_absolute_uri(obj.clock_out_photo_thumbnail_url) if request else obj.clock_out_photo_thumbnail_url

    def get_correction_by_name(self, obj):
        if not obj.corrected_by:
            return ""
        return obj.corrected_by.get_full_name() or obj.corrected_by.username

    def get_duration_display(self, obj):
        duration = obj.duration()
        if not duration:
            return ""
        total_minutes = int(duration.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours}h {minutes:02d}min"

    def get_expenses_total_display(self, obj):
        return f"{Decimal(obj.daily_expenses_total_fc or 0):,.0f} FC".replace(",", " ")

    def get_attendance_status_code(self, obj):
        return obj.get_clock_in_attendance_status()["code"]

    def get_attendance_status_label(self, obj):
        return obj.get_clock_in_attendance_status()["label"]

    def get_attendance_status_detail(self, obj):
        return obj.get_clock_in_attendance_status()["detail"]

    def get_clock_out_status_code(self, obj):
        return obj.get_clock_out_attendance_status()["code"]

    def get_clock_out_status_label(self, obj):
        return obj.get_clock_out_attendance_status()["label"]

    def get_clock_out_status_detail(self, obj):
        return obj.get_clock_out_attendance_status()["detail"]


class EmployeeShiftHistorySerializer(serializers.ModelSerializer):
    date_display = serializers.SerializerMethodField()
    clock_in_display = serializers.SerializerMethodField()
    clock_out_display = serializers.SerializerMethodField()
    duration_display = serializers.SerializerMethodField()
    report_status_label = serializers.SerializerMethodField()
    attendance_status_code = serializers.SerializerMethodField()
    attendance_status_label = serializers.SerializerMethodField()
    attendance_status_detail = serializers.SerializerMethodField()
    clock_out_status_code = serializers.SerializerMethodField()
    clock_out_status_label = serializers.SerializerMethodField()
    clock_out_status_detail = serializers.SerializerMethodField()
    clock_in_photo_url = serializers.SerializerMethodField()
    clock_out_photo_url = serializers.SerializerMethodField()
    clock_in_photo_thumbnail_url = serializers.SerializerMethodField()
    clock_out_photo_thumbnail_url = serializers.SerializerMethodField()
    clock_in_photo_taken_display = serializers.SerializerMethodField()
    clock_out_photo_taken_display = serializers.SerializerMethodField()

    class Meta:
        model = ShiftDay
        fields = [
            "id",
            "date",
            "date_display",
            "clock_in_display",
            "clock_out_display",
            "clock_in_photo_url",
            "clock_out_photo_url",
            "clock_in_photo_thumbnail_url",
            "clock_out_photo_thumbnail_url",
            "clock_in_photo_taken_display",
            "clock_out_photo_taken_display",
            "clock_in_gps_status",
            "clock_out_gps_status",
            "daily_report_confirmed",
            "total_lavages_reported",
            "duration_display",
            "report_status_label",
            "attendance_status_code",
            "attendance_status_label",
            "attendance_status_detail",
            "clock_out_status_code",
            "clock_out_status_label",
            "clock_out_status_detail",
        ]

    def get_date_display(self, obj):
        return obj.date.strftime("%d/%m/%Y")

    def get_clock_in_display(self, obj):
        return timezone.localtime(obj.clock_in_time).strftime("%H:%M") if obj.clock_in_time else ""

    def get_clock_out_display(self, obj):
        return timezone.localtime(obj.clock_out_time).strftime("%H:%M") if obj.clock_out_time else ""

    def get_clock_in_photo_url(self, obj):
        return _absolute_media_url(self.context.get("request"), obj.clock_in_photo)

    def get_clock_out_photo_url(self, obj):
        return _absolute_media_url(self.context.get("request"), obj.clock_out_photo)

    def get_clock_in_photo_thumbnail_url(self, obj):
        request = self.context.get("request")
        if not obj.clock_in_photo_thumbnail_url:
            return ""
        return request.build_absolute_uri(obj.clock_in_photo_thumbnail_url) if request else obj.clock_in_photo_thumbnail_url

    def get_clock_out_photo_thumbnail_url(self, obj):
        request = self.context.get("request")
        if not obj.clock_out_photo_thumbnail_url:
            return ""
        return request.build_absolute_uri(obj.clock_out_photo_thumbnail_url) if request else obj.clock_out_photo_thumbnail_url

    def get_clock_in_photo_taken_display(self, obj):
        return timezone.localtime(obj.clock_in_photo_taken_at).strftime("%d/%m/%Y %H:%M") if obj.clock_in_photo_taken_at else ""

    def get_clock_out_photo_taken_display(self, obj):
        return timezone.localtime(obj.clock_out_photo_taken_at).strftime("%d/%m/%Y %H:%M") if obj.clock_out_photo_taken_at else ""

    def get_duration_display(self, obj):
        duration = obj.duration()
        if not duration:
            return ""
        total_minutes = int(duration.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours}h {minutes:02d}min"

    def get_report_status_label(self, obj):
        if obj.daily_report_confirmed:
            return "Envoyé"
        if obj.clock_in_time:
            return "En attente"
        return "Non démarré"

    def get_attendance_status_code(self, obj):
        return obj.get_clock_in_attendance_status()["code"]

    def get_attendance_status_label(self, obj):
        return obj.get_clock_in_attendance_status()["label"]

    def get_attendance_status_detail(self, obj):
        return obj.get_clock_in_attendance_status()["detail"]

    def get_clock_out_status_code(self, obj):
        return obj.get_clock_out_attendance_status()["code"]

    def get_clock_out_status_label(self, obj):
        return obj.get_clock_out_attendance_status()["label"]

    def get_clock_out_status_detail(self, obj):
        return obj.get_clock_out_attendance_status()["detail"]


class EmployeeWaterPurchaseSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    purchase_date_display = serializers.SerializerMethodField()
    billing_month_display = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    week_label = serializers.SerializerMethodField()
    is_general_month_entry = serializers.SerializerMethodField()

    class Meta:
        model = SiteWaterPurchase
        fields = [
            "id",
            "supplier_name",
            "purchase_date",
            "purchase_date_display",
            "billing_month",
            "billing_month_display",
            "created_by_name",
            "notes",
            "week_label",
            "is_general_month_entry",
        ]

    def get_purchase_date_display(self, obj):
        return obj.purchase_date.strftime("%d/%m/%Y")

    def get_billing_month_display(self, obj):
        return obj.billing_month.strftime("%m/%Y")

    def get_created_by_name(self, obj):
        if not obj.created_by:
            return ""
        return obj.created_by.get_full_name() or obj.created_by.username

    def get_week_label(self, obj):
        report_date = obj.get_reporting_week_date()
        if not report_date:
            return ""
        week_start = report_date - timedelta(days=report_date.weekday())
        week_end = week_start + timedelta(days=6)
        return f"Semaine du {week_start:%d/%m} au {week_end:%d/%m}"

    def get_is_general_month_entry(self, obj):
        return obj.get_reporting_week_date() is None


class EmployeeFuelPurchaseSerializer(serializers.ModelSerializer):
    purchase_date_display = serializers.SerializerMethodField()
    billing_month_display = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SiteFuelPurchase
        fields = [
            "id",
            "purchase_date",
            "purchase_date_display",
            "billing_month",
            "billing_month_display",
            "created_by_name",
            "notes",
        ]

    def get_purchase_date_display(self, obj):
        return obj.purchase_date.strftime("%d/%m/%Y")

    def get_billing_month_display(self, obj):
        return obj.billing_month.strftime("%m/%Y")

    def get_created_by_name(self, obj):
        if not obj.created_by:
            return ""
        return obj.created_by.get_full_name() or obj.created_by.username
