from django.contrib import admin
from .models import DailyQRToken, ShiftDay


@admin.register(DailyQRToken)
class DailyQRTokenAdmin(admin.ModelAdmin):
    list_display = ("site", "date", "actif", "created_at", "regenerated_at", "regenerated_by")
    list_filter = ("actif", "date", "site")
    search_fields = ("site__nom", "token")
    ordering = ("-date", "-created_at")
    readonly_fields = ("token", "nonce", "created_at", "regenerated_at")
    
    fieldsets = (
        ("Informations du QR", {
            "fields": ("site", "date", "actif")
        }),
        ("Sécurité", {
            "fields": ("token", "nonce"),
            "classes": ("collapse",)
        }),
        ("Régénération", {
            "fields": ("regenerated_at", "regenerated_by"),
            "classes": ("collapse",)
        }),
        ("Métadonnées", {
            "fields": ("created_at",),
            "classes": ("collapse",)
        }),
    )


@admin.register(ShiftDay)
class ShiftDayAdmin(admin.ModelAdmin):
    list_display = ("employe", "site", "date", "clock_in_time", "clock_out_time", "clock_in_gps_status", "is_complete", "daily_report_confirmed")
    list_filter = ("date", "site", "daily_report_confirmed", "clock_in_gps_status", "clock_out_gps_status")
    search_fields = ("employe__username", "employe__first_name", "employe__last_name", "site__nom")
    ordering = ("-date", "-clock_in_time")
    readonly_fields = ("created_at", "updated_at", "corrected_at")
    
    fieldsets = (
        ("Pointage", {
            "fields": ("employe", "site", "date")
        }),
        ("Entrée", {
            "fields": ("clock_in_time", "clock_in_gps_latitude", "clock_in_gps_longitude", "clock_in_gps_distance_mètres", "clock_in_gps_status")
        }),
        ("Sortie", {
            "fields": ("clock_out_time", "clock_out_gps_latitude", "clock_out_gps_longitude", "clock_out_gps_distance_mètres", "clock_out_gps_status", "daily_report_confirmed", "total_lavages_reported")
        }),
        ("Correction (Manager)", {
            "fields": ("corrected_by", "correction_reason", "corrected_at"),
            "classes": ("collapse",)
        }),
        ("Métadonnées", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    
    def is_complete(self, obj):
        return obj.is_complete()
    is_complete.boolean = True
    is_complete.short_description = "Complet"
