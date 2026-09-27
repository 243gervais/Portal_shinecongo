from django.contrib import admin

from .models import (
    Contract,
    CorporateCompany,
    CorporateContact,
    MobileEmployeeProfile,
    RecurringSchedule,
    Vehicle,
    WorkOrder,
    WorkOrderProofPhoto,
    WorkOrderVehicle,
)


class CorporateContactInline(admin.TabularInline):
    model = CorporateContact
    extra = 0


class WorkOrderVehicleInline(admin.TabularInline):
    model = WorkOrderVehicle
    extra = 0
    fields = ("vehicle", "license_plate_snapshot", "service_type", "status", "billable_amount", "currency")


@admin.register(CorporateCompany)
class CorporateCompanyAdmin(admin.ModelAdmin):
    list_display = ("legal_name", "trading_name", "telephone", "billing_email", "is_active", "updated_at")
    list_filter = ("is_active", "city", "commune")
    search_fields = ("legal_name", "trading_name", "telephone", "billing_email", "rccm", "tax_number")
    inlines = [CorporateContactInline]
    readonly_fields = ("created_at", "updated_at")


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("contract_number", "company", "status", "monthly_package_price", "included_washes_per_month", "start_date", "end_date")
    list_filter = ("status", "billing_frequency", "currency", "start_date")
    search_fields = ("contract_number", "title", "company__legal_name", "company__trading_name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("company", "created_by", "approved_by")


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("company", "license_plate", "internal_fleet_number", "vehicle_type", "make", "model", "is_active")
    list_filter = ("is_active", "vehicle_type", "company")
    search_fields = ("license_plate", "internal_fleet_number", "company__legal_name", "make", "model")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("company",)


@admin.register(RecurringSchedule)
class RecurringScheduleAdmin(admin.ModelAdmin):
    list_display = ("company", "contract", "weekday", "planned_start_time", "planned_vehicles", "is_active")
    list_filter = ("is_active", "weekday", "company")
    search_fields = ("company__legal_name", "contract__contract_number", "service_location")
    filter_horizontal = ("default_assigned_team",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ("work_order_number", "company", "scheduled_start", "status", "team_leader", "reviewed_by", "completed_at")
    list_filter = ("status", "scheduled_start", "company")
    search_fields = ("work_order_number", "company__legal_name", "contract__contract_number")
    filter_horizontal = ("assigned_employees",)
    readonly_fields = ("created_at", "updated_at", "completed_at")
    inlines = [WorkOrderVehicleInline]
    autocomplete_fields = ("company", "contract", "schedule", "team_leader", "reviewed_by", "created_by")


@admin.register(MobileEmployeeProfile)
class MobileEmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "telephone", "is_active", "quality_issues", "rewash_count")
    list_filter = ("role", "is_active")
    search_fields = ("user__username", "user__first_name", "user__last_name", "telephone")
    autocomplete_fields = ("user",)


@admin.register(WorkOrderProofPhoto)
class WorkOrderProofPhotoAdmin(admin.ModelAdmin):
    list_display = ("work_order", "photo_type", "uploaded_by", "created_at")
    list_filter = ("photo_type", "created_at")
    search_fields = ("work_order__work_order_number",)
    autocomplete_fields = ("work_order", "uploaded_by")

