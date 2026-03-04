from django.contrib import admin
from .models import Location, DailyBankDeposit, SiteDocument, SiteLossEntry


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("nom", "ville", "telephone", "gps_actif", "actif", "created_at")
    list_filter = ("actif", "ville", "gps_actif")
    search_fields = ("nom", "adresse", "telephone", "site_token")
    ordering = ("nom",)
    readonly_fields = ("id", "site_token", "created_at", "updated_at")
    
    fieldsets = (
        ("Informations du Site", {
            "fields": ("nom", "adresse", "ville", "telephone")
        }),
        ("QR Code Fixe", {
            "fields": ("site_token",),
            "description": "Token unique et permanent pour le QR code de ce site"
        }),
        ("GPS Optionnel (Anti-fraude)", {
            "fields": ("gps_actif", "latitude", "longitude", "rayon_autorisé_mètres"),
            "description": "Activer la vérification GPS pour ce site. Si désactivé, aucune vérification GPS ne sera effectuée."
        }),
        ("Statut", {
            "fields": ("actif",)
        }),
        ("Métadonnées", {
            "fields": ("id", "created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )


@admin.register(DailyBankDeposit)
class DailyBankDepositAdmin(admin.ModelAdmin):
    list_display = ("site", "date", "amount", "created_by", "created_at")
    list_filter = ("date", "site")
    search_fields = ("site__nom", "notes")
    ordering = ("-date", "-created_at")
    readonly_fields = ("created_at", "updated_at")
    
    fieldsets = (
        ("Informations", {
            "fields": ("site", "date", "amount")
        }),
        ("Détails", {
            "fields": ("notes", "created_by")
        }),
        ("Métadonnées", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )


@admin.register(SiteDocument)
class SiteDocumentAdmin(admin.ModelAdmin):
    list_display = ("site", "file_type", "title", "get_filename", "get_file_size", "uploaded_by", "uploaded_at")
    list_filter = ("file_type", "site", "uploaded_at")
    search_fields = ("title", "description", "site__nom")
    ordering = ("-uploaded_at",)
    readonly_fields = ("uploaded_at", "updated_at", "get_filename", "get_file_size")
    
    fieldsets = (
        ("Informations", {
            "fields": ("site", "file_type", "title", "description")
        }),
        ("Fichier", {
            "fields": ("file", "get_filename", "get_file_size")
        }),
        ("Métadonnées", {
            "fields": ("uploaded_by", "uploaded_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    
    def get_filename(self, obj):
        return obj.filename()
    get_filename.short_description = "Nom du fichier"
    
    def get_file_size(self, obj):
        return f"{obj.file_size_mb()} MB"
    get_file_size.short_description = "Taille"


@admin.register(SiteLossEntry)
class SiteLossEntryAdmin(admin.ModelAdmin):
    list_display = ("site", "date", "category", "funding_source", "amount", "title", "created_by", "created_at")
    list_filter = ("date", "site", "category", "funding_source")
    search_fields = ("site__nom", "title", "description")
    ordering = ("-date", "-created_at")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Informations", {
            "fields": ("site", "date", "category", "funding_source", "amount", "title")
        }),
        ("Détails", {
            "fields": ("description", "created_by")
        }),
        ("Métadonnées", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
