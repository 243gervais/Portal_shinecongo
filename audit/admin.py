from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "description_courte", "motif_court", "created_at")
    list_filter = ("action", "created_at", "user")
    search_fields = ("user__username", "description", "motif", "ip_address")
    ordering = ("-created_at",)
    readonly_fields = (
        "user", "action", "description", "content_type", "object_id",
        "motif", "donnees_avant", "donnees_apres", "ip_address", "user_agent", "created_at"
    )
    
    fieldsets = (
        ("Action", {
            "fields": ("user", "action", "description")
        }),
        ("Objet", {
            "fields": ("content_type", "object_id"),
            "classes": ("collapse",)
        }),
        ("Détails", {
            "fields": ("motif", "donnees_avant", "donnees_apres")
        }),
        ("Métadonnées Réseau", {
            "fields": ("ip_address", "user_agent"),
            "classes": ("collapse",)
        }),
        ("Horodatage", {
            "fields": ("created_at",)
        }),
    )
    
    def has_add_permission(self, request):
        # Ne pas permettre d'ajouter manuellement des entrées d'audit
        return False
    
    def has_delete_permission(self, request, obj=None):
        # Ne pas permettre de supprimer des entrées d'audit
        return False
    
    def description_courte(self, obj):
        if len(obj.description) > 50:
            return obj.description[:50] + "..."
        return obj.description
    description_courte.short_description = "Description"
    
    def motif_court(self, obj):
        if obj.motif and len(obj.motif) > 30:
            return obj.motif[:30] + "..."
        return obj.motif or "-"
    motif_court.short_description = "Motif"
