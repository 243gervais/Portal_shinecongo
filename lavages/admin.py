from django.contrib import admin
from .models import CarWash, CarWashPhoto


class CarWashPhotoInline(admin.TabularInline):
    model = CarWashPhoto
    extra = 0
    readonly_fields = ("uploaded_at",)
    fields = ("photo", "type_photo", "uploaded_at")


@admin.register(CarWash)
class CarWashAdmin(admin.ModelAdmin):
    list_display = ("employe", "site", "date", "type_service", "montant", "plaque", "photo_count", "created_at")
    list_filter = ("type_service", "date", "site")
    search_fields = ("employe__username", "employe__first_name", "employe__last_name", "plaque", "site__nom")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [CarWashPhotoInline]
    
    fieldsets = (
        ("Employé et Site", {
            "fields": ("employe", "site", "date")
        }),
        ("Service", {
            "fields": ("type_service", "plaque", "plaque_photo", "montant", "notes")
        }),
        ("Métadonnées", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    
    def photo_count(self, obj):
        return obj.photo_count()
    photo_count.short_description = "Photos"


@admin.register(CarWashPhoto)
class CarWashPhotoAdmin(admin.ModelAdmin):
    list_display = ("lavage", "type_photo", "filename", "uploaded_at")
    list_filter = ("type_photo", "uploaded_at")
    search_fields = ("lavage__employe__username", "lavage__plaque")
    ordering = ("-uploaded_at",)
    readonly_fields = ("uploaded_at",)
