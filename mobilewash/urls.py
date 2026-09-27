from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="mobilewash_dashboard"),
    path("companies/", views.companies, name="mobilewash_companies"),
    path("companies/new/", views.company_create, name="mobilewash_company_create"),
    path("companies/<int:company_id>/", views.company_detail, name="mobilewash_company_detail"),
    path("contracts/", views.contracts, name="mobilewash_contracts"),
    path("contracts/new/", views.contract_form, name="mobilewash_contract_create"),
    path("contracts/<int:contract_id>/", views.contract_detail, name="mobilewash_contract_detail"),
    path("contracts/<int:contract_id>/edit/", views.contract_form, name="mobilewash_contract_edit"),
    path("vehicles/", views.vehicles, name="mobilewash_vehicles"),
    path("vehicles/new/", views.vehicle_form, name="mobilewash_vehicle_create"),
    path("vehicles/<int:vehicle_id>/edit/", views.vehicle_form, name="mobilewash_vehicle_edit"),
    path("schedules/", views.schedules, name="mobilewash_schedules"),
    path("schedules/new/", views.schedule_form, name="mobilewash_schedule_create"),
    path("schedules/<int:schedule_id>/edit/", views.schedule_form, name="mobilewash_schedule_edit"),
    path("schedules/generate/", views.generate_schedule, name="mobilewash_generate_schedule"),
    path("work-orders/", views.work_orders, name="mobilewash_work_orders"),
    path("work-orders/new/", views.work_order_form, name="mobilewash_work_order_create"),
    path("work-orders/<int:work_order_id>/", views.work_order_detail, name="mobilewash_work_order_detail"),
    path("work-orders/<int:work_order_id>/edit/", views.work_order_form, name="mobilewash_work_order_edit"),
    path("work-orders/<int:work_order_id>/field/", views.field_work_order, name="mobilewash_field_work_order"),
    path("work-orders/<int:work_order_id>/review/", views.review_work_order, name="mobilewash_review_work_order"),
    path("work-orders/<int:work_order_id>/receipt.pdf", views.service_receipt_pdf, name="mobilewash_service_receipt_pdf"),
]

