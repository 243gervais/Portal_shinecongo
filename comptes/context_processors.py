from django.core.cache import cache
from django.db.models import Count, Max
from django.urls import reverse
from django.utils import timezone

from comptes.admin_inbox import ensure_admin_profile, get_admin_inbox_counts
from comptes.models import UserProfile
from sites.models import Location


def _is_world_cup_login_theme_active(current_date):
    return current_date.month == 6 and current_date.day >= 11


def _stamp_for_cache(value):
    if value is None:
        return "none"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _is_admin_user(user):
    if not user.is_authenticated:
        return False

    profile = ensure_admin_profile(user)
    return user.is_superuser or (profile and profile.is_admin())


def _build_admin_site_navigation(request):
    user = request.user

    if not _is_admin_user(user):
        return {
            "show_admin_site_nav": False,
            "admin_site_nav_label": "",
            "admin_site_nav_sections": [],
            "admin_site_search_items": [],
        }

    resolver_match = getattr(request, "resolver_match", None)
    current_site_id = None
    if resolver_match:
        current_site_id = resolver_match.kwargs.get("site_id")

    today = timezone.localdate()
    site_meta = Location.objects.filter(actif=True).aggregate(total=Count("id"), latest=Max("updated_at"))
    if not site_meta["total"]:
        return {
            "show_admin_site_nav": False,
            "admin_site_nav_label": "",
            "admin_site_nav_sections": [],
            "admin_site_search_items": [],
        }

    employee_qs = UserProfile.objects.filter(
        site__actif=True,
        role__in=UserProfile.SITE_STAFF_ROLES,
        actif=True,
    )
    employee_meta = employee_qs.aggregate(total=Count("id"), latest=Max("updated_at"))
    can_view_company_secrets = user.is_superuser or user.username == "gervaismbadu"
    cache_key = ":".join(
        [
            "admin-site-nav-v2",
            str(current_site_id or "none"),
            today.isoformat(),
            str(can_view_company_secrets),
            str(site_meta["total"]),
            _stamp_for_cache(site_meta["latest"]),
            str(employee_meta["total"]),
            _stamp_for_cache(employee_meta["latest"]),
        ]
    )
    cached_navigation = cache.get(cache_key)
    if cached_navigation is not None:
        return cached_navigation

    sites = list(Location.objects.filter(actif=True).only("id", "nom").order_by("nom"))
    current_site = next((site for site in sites if str(site.id) == str(current_site_id)), None)
    primary_site = current_site or sites[0]

    employee_profiles = (
        employee_qs
        .select_related("site", "user")
        .only(
            "id",
            "site_id",
            "role",
            "site__id",
            "site__nom",
            "user__id",
            "user__first_name",
            "user__last_name",
            "user__username",
        )
        .order_by("site__nom", "user__first_name", "user__last_name", "user__username")
    )
    employees_by_site = {}
    for profile in employee_profiles:
        employees_by_site.setdefault(str(profile.site_id), []).append(profile)

    def build_search_item(label, url, site_name="", description="", keywords=""):
        return {
            "label": label,
            "url": url,
            "site_name": site_name,
            "description": description,
            "search_text": " ".join(filter(None, [label, site_name, description, keywords])),
        }

    search_items = [
        build_search_item(
            "Boite Admin",
            reverse("admin_dashboard"),
            description="Demandes de comptes et messages",
            keywords="dashboard admin demandes rapports compte pending",
        ),
        build_search_item(
            "Messages",
            reverse("admin_messages"),
            description="Rappels du portail, shinecongo.org et anniversaires employés",
            keywords="messages rappels notifications portail website shinecongo.org anniversaires employes admin",
        ),
        build_search_item(
            "Historique rapports fin de journée",
            reverse("admin_daily_report_history"),
            description="Historique quotidien et mensuel des messages employés",
            keywords="rapports fin de journée historique messages employes journalier mensuel",
        ),
        build_search_item(
            "Suivi eau",
            reverse("admin_water_purchases"),
            description="Achats d'eau et mois concerné",
            keywords="eau achats eau forage reservoir mois concerné",
        ),
        build_search_item(
            "Mots de passe",
            reverse("admin_password_management"),
            description="Changer les mots de passe des comptes admin, managers, employés et contrôleurs caméra",
            keywords="mot de passe password comptes admin manager employe camera controleur site",
        ),
        build_search_item(
            "Convertisseur USD/FC",
            f"{reverse('admin_dashboard')}#admin-fx-tools",
            description="Taux et conversion devise",
            keywords="usd fc cdf franc congolais dollar convertisseur taux devise",
        ),
    ]
    if can_view_company_secrets:
        search_items.append(
            build_search_item(
                "Coffre top secret",
                reverse("admin_company_secret_documents"),
                description="Documents hautement confidentiels de l'entreprise",
                keywords="top secret confidentiel documents entreprise special important coffre",
            )
        )

    site_sections = []
    for site in sites:
        site_id = str(site.id)
        site_detail_url = reverse("admin_site_detail", kwargs={"site_id": site.id})
        site_losses_url = f"{reverse('admin_site_losses', kwargs={'site_id': site.id})}?date={today:%Y-%m-%d}"
        site_bank_deposit_url = f"{reverse('admin_add_bank_deposit', kwargs={'site_id': site.id})}?date={today:%Y-%m-%d}"
        site_items = [
            *(
                [
                    {
                        "label": "Coffre top secret",
                        "url": reverse("admin_company_secret_documents"),
                        "description": "Documents hautement confidentiels de l'entreprise",
                        "keywords": "top secret confidentiel documents entreprise special important coffre",
                    }
                ]
                if can_view_company_secrets else []
            ),
            {
                "label": "Vue site",
                "url": site_detail_url,
                "description": "Aperçu complet du site",
                "keywords": "vue site command center overview",
            },
            {
                "label": "Pilotage hebdomadaire",
                "url": f"{site_detail_url}#pilotage-hebdomadaire",
                "description": "Cash flow, banque et pertes",
                "keywords": "pilotage hebdomadaire cash flow banque pertes",
            },
            {
                "label": "Historique comparatif",
                "url": reverse("admin_site_history_comparison", kwargs={"site_id": site.id}),
                "description": "Comparaison semaine, mois et année",
                "keywords": "historique comparatif hebdomadaire mensuel annuel graphes banque pertes cash flow",
            },
            {
                "label": "Synthèse opérationnelle",
                "url": f"{site_detail_url}#synthese-operationnelle",
                "description": "Résumé du site",
                "keywords": "synthese operations resume production",
            },
            {
                "label": "Corrections & finance",
                "url": site_losses_url,
                "description": "Pertes, dépôts et corrections",
                "keywords": "finance pertes depot banque corrections",
            },
            {
                "label": "Gestion des employés",
                "url": reverse("admin_site_employees", kwargs={"site_id": site.id}),
                "description": "Équipe site, salaires, paiements et rôles",
                "keywords": "employes equipe camera controle salaire productivite paiements mpesa rh",
            },
            {
                "label": "Caméras & comptage",
                "url": reverse("admin_site_camera_monitoring", kwargs={"site_id": site.id}),
                "description": "Caméras du site, comptage manuel et preuves vidéo",
                "keywords": "camera monitoring comptage voitures motos videos preuves s3",
            },
            {
                "label": "Documents du site",
                "url": reverse("admin_site_documents", kwargs={"site_id": site.id}),
                "description": "Documents, médias et bibliothèque",
                "keywords": "documents fichiers photos medias bibliotheque site",
            },
            {
                "label": "Journal du site",
                "url": reverse("admin_site_journal", kwargs={"site_id": site.id}),
                "description": "Informations et notes du site",
                "keywords": "journal notes informations depenses",
            },
            {
                "label": "Ajouter un lavage",
                "url": reverse("admin_add_wash", kwargs={"site_id": site.id}),
                "description": "Créer un lavage en admin",
                "keywords": "lavage ajouter voiture",
            },
            {
                "label": "Ajouter total quotidien",
                "url": reverse("admin_add_daily_total", kwargs={"site_id": site.id}),
                "description": "Corriger le total de la journée",
                "keywords": "total quotidien rapport journee",
            },
            {
                "label": "Ajouter dépôt bancaire",
                "url": site_bank_deposit_url,
                "description": "Saisir le dépôt du jour",
                "keywords": "depot banque argent jour",
            },
            {
                "label": "Historique des lavages",
                "url": f"{site_detail_url}#historique-lavages",
                "description": "Liste complète des lavages",
                "keywords": "historique lavages liste voitures",
            },
            {
                "label": "Pointages",
                "url": f"{site_detail_url}#pointages-site",
                "description": "Présences et horaires",
                "keywords": "pointages presence horaires",
            },
            {
                "label": "Problèmes signalés",
                "url": f"{site_detail_url}#problemes-signales",
                "description": "Incidents déclarés",
                "keywords": "problemes signales incidents",
            },
            {
                "label": "Problèmes ouverts",
                "url": f"{site_detail_url}#problemes-ouverts",
                "description": "Incidents actifs",
                "keywords": "problemes ouverts incidents actifs",
            },
            {
                "label": "Photos des lavages",
                "url": f"{site_detail_url}#photos-lavages",
                "description": "Galerie des preuves photo",
                "keywords": "photos lavage galerie images",
            },
            {
                "label": "Ajouter membre",
                "url": reverse("admin_add_site_employee", kwargs={"site_id": site.id}),
                "description": "Créer un employé lavage ou un contrôleur caméra",
                "keywords": "employe camera controleur ajouter salaire mpesa",
            },
        ]

        employee_links = []
        for profile in employees_by_site.get(site_id, []):
            employee_name = profile.user.get_full_name() or profile.user.username
            employee_url = reverse(
                "admin_site_employee_portal",
                kwargs={"site_id": site.id, "profile_id": profile.id},
            )
            employee_links.append(
                {
                    "label": f"{employee_name} · {profile.get_role_display()}",
                    "url": employee_url,
                }
            )
            search_items.append(
                build_search_item(
                    f"Équipe {employee_name}",
                    employee_url,
                    site_name=site.nom,
                    description=f"Portail {profile.get_role_display().lower()}",
                    keywords=f"employe camera salaire paiement mpesa fiche {employee_name}",
                )
            )

        for item in site_items:
            search_items.append(
                build_search_item(
                    item["label"],
                    item["url"],
                    site_name=site.nom,
                    description=item["description"],
                    keywords=item["keywords"],
                )
            )

        site_sections.append(
            {
                "site_name": site.nom,
                "detail_url": site_detail_url,
                "is_primary": str(primary_site.id) == site_id,
                "items": site_items,
                "employee_links": employee_links,
            }
        )

    navigation_context = {
        "show_admin_site_nav": True,
        "admin_site_nav_label": primary_site.nom,
        "admin_site_nav_sections": site_sections,
        "admin_site_search_items": search_items,
    }
    cache.set(cache_key, navigation_context, 300)
    return navigation_context


def _build_employee_portal_revision(user):
    # Disabled on purpose: the old revision token triggered extra aggregate queries
    # on every employee page while the instant-navigation prefetch layer was active.
    return ""


def admin_inbox_badge(request):
    context = get_admin_inbox_counts(request.user)
    context.update(_build_admin_site_navigation(request))
    context["portal_activity_revision"] = _build_employee_portal_revision(request.user)
    return context
