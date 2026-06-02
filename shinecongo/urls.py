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
from comptes.views import (
    dashboard,
    logout_view,
    register_view,
    admin_dashboard,
    admin_messages,
    admin_resolve_reminder,
    admin_delete_reminder,
    admin_daily_report_history,
    admin_password_management,
    admin_change_user_password,
    admin_water_purchases,
    admin_edit_water_purchase,
    admin_move_water_purchase,
    admin_edit_water_supplier,
    admin_delete_water_purchase,
    admin_approve_account_request,
    admin_reject_account_request,
    admin_site_detail,
    admin_site_history_comparison,
    admin_create_site,
    admin_add_wash,
    admin_edit_wash,
    admin_delete_wash,
    admin_add_daily_total,
    admin_add_bank_deposit,
    admin_delete_bank_deposit,
    admin_site_losses,
    admin_add_site_loss,
    admin_edit_site_loss,
    admin_delete_site_loss,
    admin_edit_pointage,
    admin_delete_pointage,
    admin_delete_daily_report,
    admin_site_documents,
    admin_site_camera_monitoring,
    admin_edit_site_camera,
    admin_site_camera_report_detail,
    admin_delete_video_evidence,
    admin_site_employees,
    admin_site_journal,
    admin_edit_site_journal_entry,
    admin_move_site_journal_entry,
    admin_delete_site_journal_entry,
    admin_site_employee_portal,
    admin_add_site_employee,
    admin_edit_site_employee,
    admin_remove_site_employee,
    admin_create_employee_payment,
    admin_employee_payment_receipt,
    admin_employee_payment_receipt_pdf,
    shared_employee_payment_receipt,
    shared_employee_payment_receipt_pdf,
    admin_upload_site_document,
    admin_edit_site_document,
    admin_delete_site_document,
)
from comptes.forms import ApprovalAuthenticationForm

# Personnalisation de l'admin Django en français
admin.site.site_header = "Shine Congo - Administration"
admin.site.site_title = "Shine Congo Admin"
admin.site.index_title = "Portail Opérations Employés"

# Importations des vues
from pointage.views import (
    employe_dashboard, scan_qr_clock_in, scan_qr_clock_out, employe_historique, scan_qr_fixe, employe_daily_report,
    employe_water_purchase,
)
from pointage.views_manager import (
    manager_dashboard, manager_qr_du_jour, manager_regenerer_qr,
    manager_pointages, manager_corriger_pointage, manager_lavages, manager_problemes
)
from lavages.views import ajouter_lavage, mes_lavages, detail_lavage
from problemes.views import signaler_probleme, mes_problemes, detail_probleme
from sites.views import (
    admin_camera_controller_portal,
    admin_camera_operator_report_detail,
    camera_dashboard,
    camera_daily_report,
    camera_delete_observation,
)

urlpatterns = [
    # Admin Django
    path("admin/", admin.site.urls),
    
    # Authentication
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="auth/login.html",
            authentication_form=ApprovalAuthenticationForm
        ),
        name="login",
    ),
    path("register/", register_view, name="register"),
    path("logout/", logout_view, name="logout"),
    
    # Dashboard principal (redirige selon le rôle)
    path("", dashboard, name="dashboard"),
    
    # PORTAIL EMPLOYÉ
    path("employe/", employe_dashboard, name="employe_dashboard"),
    path("employe/scan-in/", scan_qr_clock_in, name="scan_qr_clock_in"),
    path("employe/scan-out/", scan_qr_clock_out, name="scan_qr_clock_out"),
    path("employe/rapport-journee/", employe_daily_report, name="employe_daily_report"),
    path("employe/eau/", employe_water_purchase, name="employe_water_purchase"),
    path("employe/historique/", employe_historique, name="employe_historique"),
    path("camera/", camera_dashboard, name="camera_dashboard"),
    path("camera/lavage-verification/", camera_daily_report, name="camera_lavage_verification"),
    path("camera/rapport/", camera_daily_report, name="camera_daily_report"),
    path("camera/observations/<int:observation_id>/delete/", camera_delete_observation, name="camera_delete_observation"),
    
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
    
    # PORTAIL ADMIN
    path("admin-dashboard/", admin_dashboard, name="admin_dashboard"),
    path("admin-dashboard/messages/", admin_messages, name="admin_messages"),
    path("admin-dashboard/reminders/<int:reminder_id>/resolve/", admin_resolve_reminder, name="admin_resolve_reminder"),
    path("admin-dashboard/reminders/<int:reminder_id>/delete/", admin_delete_reminder, name="admin_delete_reminder"),
    path("admin-dashboard/daily-reports/history/", admin_daily_report_history, name="admin_daily_report_history"),
    path("admin-dashboard/passwords/", admin_password_management, name="admin_password_management"),
    path("admin-dashboard/passwords/<int:user_id>/", admin_change_user_password, name="admin_change_user_password"),
    path("admin-dashboard/water-purchases/", admin_water_purchases, name="admin_water_purchases"),
    path("admin-dashboard/water-purchases/<int:purchase_id>/edit/", admin_edit_water_purchase, name="admin_edit_water_purchase"),
    path("admin-dashboard/water-purchases/<int:purchase_id>/move/", admin_move_water_purchase, name="admin_move_water_purchase"),
    path("admin-dashboard/water-suppliers/<int:supplier_id>/edit/", admin_edit_water_supplier, name="admin_edit_water_supplier"),
    path("admin-dashboard/water-purchases/<int:purchase_id>/delete/", admin_delete_water_purchase, name="admin_delete_water_purchase"),
    path("admin-dashboard/account-requests/<int:user_id>/approve/", admin_approve_account_request, name="admin_approve_account_request"),
    path("admin-dashboard/account-requests/<int:user_id>/reject/", admin_reject_account_request, name="admin_reject_account_request"),
    path("admin-dashboard/site/create/", admin_create_site, name="admin_create_site"),
    path("admin-dashboard/site/<uuid:site_id>/", admin_site_detail, name="admin_site_detail"),
    path("admin-dashboard/site/<uuid:site_id>/historique-comparatif/", admin_site_history_comparison, name="admin_site_history_comparison"),
    path("admin-dashboard/site/<uuid:site_id>/add-wash/", admin_add_wash, name="admin_add_wash"),
    path("admin-dashboard/site/<uuid:site_id>/lavages/<int:lavage_id>/edit/", admin_edit_wash, name="admin_edit_wash"),
    path("admin-dashboard/site/<uuid:site_id>/lavages/<int:lavage_id>/delete/", admin_delete_wash, name="admin_delete_wash"),
    path("admin-dashboard/site/<uuid:site_id>/add-daily-total/", admin_add_daily_total, name="admin_add_daily_total"),
    path("admin-dashboard/site/<uuid:site_id>/add-bank-deposit/", admin_add_bank_deposit, name="admin_add_bank_deposit"),
    path("admin-dashboard/site/<uuid:site_id>/bank-deposits/<int:deposit_id>/delete/", admin_delete_bank_deposit, name="admin_delete_bank_deposit"),
    path("admin-dashboard/site/<uuid:site_id>/losses/", admin_site_losses, name="admin_site_losses"),
    path("admin-dashboard/site/<uuid:site_id>/losses/add/", admin_add_site_loss, name="admin_add_site_loss"),
    path("admin-dashboard/site/<uuid:site_id>/losses/<int:loss_id>/edit/", admin_edit_site_loss, name="admin_edit_site_loss"),
    path("admin-dashboard/site/<uuid:site_id>/losses/<int:loss_id>/delete/", admin_delete_site_loss, name="admin_delete_site_loss"),
    path("admin-dashboard/site/<uuid:site_id>/pointages/<int:pointage_id>/edit/", admin_edit_pointage, name="admin_edit_pointage"),
    path("admin-dashboard/site/<uuid:site_id>/pointages/<int:pointage_id>/delete/", admin_delete_pointage, name="admin_delete_pointage"),
    path("admin-dashboard/site/<uuid:site_id>/pointages/<int:pointage_id>/delete-report/", admin_delete_daily_report, name="admin_delete_daily_report"),
    path("admin-dashboard/site/<uuid:site_id>/documents/", admin_site_documents, name="admin_site_documents"),
    path("admin-dashboard/site/<uuid:site_id>/camera-monitoring/", admin_site_camera_monitoring, name="admin_site_camera_monitoring"),
    path("admin-dashboard/site/<uuid:site_id>/cameras/<int:camera_id>/edit/", admin_edit_site_camera, name="admin_edit_site_camera"),
    path("admin-dashboard/site/<uuid:site_id>/camera-reports/<int:report_id>/", admin_site_camera_report_detail, name="admin_site_camera_report_detail"),
    path("admin-dashboard/site/<uuid:site_id>/camera-controllers/<int:profile_id>/portal/", admin_camera_controller_portal, name="admin_camera_controller_portal"),
    path("admin-dashboard/site/<uuid:site_id>/camera-operator-reports/<int:report_id>/", admin_camera_operator_report_detail, name="admin_camera_operator_report_detail"),
    path("admin-dashboard/site/<uuid:site_id>/camera-evidence/<int:evidence_id>/delete/", admin_delete_video_evidence, name="admin_delete_video_evidence"),
    path("admin-dashboard/site/<uuid:site_id>/employees/", admin_site_employees, name="admin_site_employees"),
    path("admin-dashboard/site/<uuid:site_id>/journal/", admin_site_journal, name="admin_site_journal"),
    path("admin-dashboard/site/<uuid:site_id>/journal/<int:entry_id>/edit/", admin_edit_site_journal_entry, name="admin_edit_site_journal_entry"),
    path("admin-dashboard/site/<uuid:site_id>/journal/<int:entry_id>/move/", admin_move_site_journal_entry, name="admin_move_site_journal_entry"),
    path("admin-dashboard/site/<uuid:site_id>/journal/<int:entry_id>/delete/", admin_delete_site_journal_entry, name="admin_delete_site_journal_entry"),
    path("admin-dashboard/site/<uuid:site_id>/employees/<int:profile_id>/portal/", admin_site_employee_portal, name="admin_site_employee_portal"),
    path("admin-dashboard/site/<uuid:site_id>/employees/add/", admin_add_site_employee, name="admin_add_site_employee"),
    path("admin-dashboard/site/<uuid:site_id>/employees/<int:profile_id>/edit/", admin_edit_site_employee, name="admin_edit_site_employee"),
    path("admin-dashboard/site/<uuid:site_id>/employees/<int:profile_id>/remove/", admin_remove_site_employee, name="admin_remove_site_employee"),
    path("admin-dashboard/site/<uuid:site_id>/employees/<int:profile_id>/payment/", admin_create_employee_payment, name="admin_create_employee_payment"),
    path("admin-dashboard/site/<uuid:site_id>/payments/<int:payment_id>/fiche/", admin_employee_payment_receipt, name="admin_employee_payment_receipt"),
    path("admin-dashboard/site/<uuid:site_id>/payments/<int:payment_id>/fiche/pdf/", admin_employee_payment_receipt_pdf, name="admin_employee_payment_receipt_pdf"),
    path("admin-dashboard/site/<uuid:site_id>/documents/upload/", admin_upload_site_document, name="admin_upload_site_document"),
    path("admin-dashboard/site/<uuid:site_id>/documents/<int:document_id>/edit/", admin_edit_site_document, name="admin_edit_site_document"),
    path("admin-dashboard/site/<uuid:site_id>/documents/<int:document_id>/delete/", admin_delete_site_document, name="admin_delete_site_document"),
    path("shared/payment-receipts/<str:token>/", shared_employee_payment_receipt, name="shared_employee_payment_receipt"),
    path("shared/payment-receipts/<str:token>/pdf/", shared_employee_payment_receipt_pdf, name="shared_employee_payment_receipt_pdf"),
]

# Servir les fichiers media en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
