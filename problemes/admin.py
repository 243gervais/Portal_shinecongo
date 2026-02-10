from django.contrib import admin
from django.utils import timezone
from .models import IssueReport


@admin.register(IssueReport)
class IssueReportAdmin(admin.ModelAdmin):
    list_display = ("employe", "site", "categorie", "statut", "created_at", "traite_par", "resolu_le")
    list_filter = ("statut", "categorie", "site", "created_at")
    search_fields = ("employe__username", "employe__first_name", "employe__last_name", "description", "site__nom")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    
    fieldsets = (
        ("Problème", {
            "fields": ("employe", "site", "categorie", "description", "photo")
        }),
        ("Traitement", {
            "fields": ("statut", "traite_par", "notes_resolution", "resolu_le")
        }),
        ("Métadonnées", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    
    actions = ["marquer_en_cours", "marquer_resolu"]
    
    def marquer_en_cours(self, request, queryset):
        queryset.update(statut="EN_COURS", traite_par=request.user)
        self.message_user(request, f"{queryset.count()} problème(s) marqué(s) comme 'En cours'")
    marquer_en_cours.short_description = "Marquer comme 'En cours'"
    
    def marquer_resolu(self, request, queryset):
        queryset.update(
            statut="RESOLU",
            traite_par=request.user,
            resolu_le=timezone.now()
        )
        self.message_user(request, f"{queryset.count()} problème(s) marqué(s) comme 'Résolu'")
    marquer_resolu.short_description = "Marquer comme 'Résolu'"
