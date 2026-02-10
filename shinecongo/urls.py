"""
URL configuration for shinecongo project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from comptes.views import dashboard, logout_view, register_view

# Personnalisation de l'admin Django en français
admin.site.site_header = "Shine Congo - Administration"
admin.site.site_title = "Shine Congo Admin"
admin.site.index_title = "Portail Opérations Employés"

# Importations des vues
from pointage.views import (
    employe_dashboard, scan_qr_clock_in, scan_qr_clock_out, employe_historique, scan_qr_fixe
)
from pointage.views_manager import (
    manager_dashboard, manager_qr_du_jour, manager_regenerer_qr,
    manager_pointages, manager_corriger_pointage, manager_lavages, manager_problemes
)
from lavages.views import ajouter_lavage, mes_lavages, detail_lavage
from problemes.views import signaler_probleme, mes_problemes, detail_probleme

urlpatterns = [
    # Admin Django
    path("admin/", admin.site.urls),
    
    # Authentication
    path("login/", auth_views.LoginView.as_view(template_name="auth/login.html"), name="login"),
    path("register/", register_view, name="register"),
    path("logout/", logout_view, name="logout"),
    
    # Dashboard principal (redirige selon le rôle)
    path("", dashboard, name="dashboard"),
    
    # PORTAIL EMPLOYÉ
    path("employe/", employe_dashboard, name="employe_dashboard"),
    path("employe/scan-in/", scan_qr_clock_in, name="scan_qr_clock_in"),
    path("employe/scan-out/", scan_qr_clock_out, name="scan_qr_clock_out"),
    path("employe/historique/", employe_historique, name="employe_historique"),
    
    # Scan QR fixe (URL publique pour le QR code)
    path("scan/<uuid:site_token>/", scan_qr_fixe, name="scan_qr_fixe"),
    
    # Lavages (employé)
    path("employe/lavage/ajouter/", ajouter_lavage, name="ajouter_lavage"),
    path("employe/lavage/mes-lavages/", mes_lavages, name="mes_lavages"),
    path("employe/lavage/<int:lavage_id>/", detail_lavage, name="detail_lavage"),
    
    # Problèmes (employé)
    path("employe/probleme/signaler/", signaler_probleme, name="signaler_probleme"),
    path("employe/probleme/mes-problemes/", mes_problemes, name="mes_problemes"),
    path("employe/probleme/<int:probleme_id>/", detail_probleme, name="detail_probleme"),
    
    # PORTAIL MANAGER
    path("manager/", manager_dashboard, name="manager_dashboard"),
    path("manager/qr/<uuid:site_id>/", manager_qr_du_jour, name="manager_qr_du_jour"),
    path("manager/qr/<uuid:site_id>/regenerer/", manager_regenerer_qr, name="manager_regenerer_qr"),
    path("manager/pointages/", manager_pointages, name="manager_pointages"),
    path("manager/pointages/<int:pointage_id>/corriger/", manager_corriger_pointage, name="manager_corriger_pointage"),
    path("manager/lavages/", manager_lavages, name="manager_lavages"),
    path("manager/problemes/", manager_problemes, name="manager_problemes"),
    
    # PORTAIL ADMIN (utilise l'interface Django Admin pour l'instant)
    # path("admin-dashboard/", admin_dashboard, name="admin_dashboard"),
]

# Servir les fichiers media en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

