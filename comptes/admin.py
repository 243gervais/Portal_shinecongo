from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils.crypto import get_random_string
from django.urls import path
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.utils.html import format_html
from django.urls import reverse
from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profil"
    fk_name = "user"
    fields = ("role", "site", "telephone", "actif")


class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "get_role", "get_site", "password_reset_link")
    list_filter = ("is_staff", "is_superuser", "is_active", "userprofile__role", "userprofile__site")
    actions = ["reset_passwords"]
    
    # Les fieldsets par défaut de BaseUserAdmin incluent déjà le champ password
    # qui affiche un lien pour changer le mot de passe sans ancien mot de passe
    
    def get_role(self, obj):
        if hasattr(obj, "userprofile"):
            return obj.userprofile.get_role_display()
        return "-"
    get_role.short_description = "Rôle"
    
    def get_site(self, obj):
        if hasattr(obj, "userprofile"):
            return obj.userprofile.site
        return "-"
    get_site.short_description = "Site"
    
    def password_reset_link(self, obj):
        """Lien pour réinitialiser le mot de passe sans ancien mot de passe"""
        url = reverse('admin:comptes_user_change_password', args=[obj.pk])
        return format_html('<a href="{}" class="button" style="background: linear-gradient(135deg, #0066FF, #0052CC); color: white; padding: 0.5rem 1rem; border-radius: 6px; text-decoration: none; font-weight: 600;">Réinitialiser mot de passe</a>', url)
    password_reset_link.short_description = "Mot de passe"
    password_reset_link.allow_tags = True
    
    def get_urls(self):
        """Ajouter une URL personnalisée pour changer le mot de passe"""
        urls = super().get_urls()
        custom_urls = [
            path(
                '<id>/password-change/',
                self.admin_site.admin_view(self.user_change_password),
                name='comptes_user_change_password',
            ),
        ]
        return custom_urls + urls
    
    def user_change_password(self, request, id):
        """Vue pour changer le mot de passe d'un utilisateur sans ancien mot de passe"""
        user = get_object_or_404(User, pk=id)
        
        if request.method == 'POST':
            form = AdminPasswordChangeForm(user, request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, f'Le mot de passe de {user.username} a été modifié avec succès.')
                return redirect('admin:auth_user_change', user.pk)
        else:
            form = AdminPasswordChangeForm(user)
        
        context = {
            'title': f'Changer le mot de passe de {user.username}',
            'form': form,
            'user': user,
            'opts': self.model._meta,
            'has_view_permission': self.has_view_permission(request, user),
            'has_change_permission': self.has_change_permission(request, user),
            'site_header': self.admin_site.site_header,
            'site_title': self.admin_site.site_title,
            'has_absolute_url': False,
        }
        
        return render(request, 'admin/auth/user/change_password.html', context)
    
    def reset_passwords(self, request, queryset):
        """Action pour réinitialiser les mots de passe de plusieurs utilisateurs"""
        count = 0
        reset_passwords = []
        
        for user in queryset:
            # Générer un nouveau mot de passe aléatoire
            new_password = get_random_string(length=8)
            user.set_password(new_password)
            user.save()
            reset_passwords.append({
                'username': user.username,
                'password': new_password
            })
            count += 1
        
        # Créer un message avec les nouveaux mots de passe
        message_parts = [f"{count} mot(s) de passe réinitialisé(s).\n\n"]
        message_parts.append("Nouveaux mots de passe :\n")
        for item in reset_passwords:
            message_parts.append(f"  • {item['username']}: {item['password']}\n")
        
        messages.success(request, ''.join(message_parts))
        
        # Afficher aussi dans la console pour faciliter la copie
        print("\n" + "="*60)
        print("MOTS DE PASSE RÉINITIALISÉS")
        print("="*60)
        for item in reset_passwords:
            print(f"Utilisateur: {item['username']}")
            print(f"Mot de passe: {item['password']}")
            print("-" * 60)
    
    reset_passwords.short_description = "Réinitialiser les mots de passe (afficher les nouveaux)"


# Unregister the default User admin and register the custom one
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "site", "telephone", "actif", "created_at")
    list_filter = ("role", "site", "actif")
    search_fields = ("user__username", "user__first_name", "user__last_name", "telephone")
    ordering = ("-created_at",)
