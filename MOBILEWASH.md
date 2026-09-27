# Lavage mobile corporate

Cette extension ajoute le modele operationnel corporate mobile sans modifier les donnees du lavage fixe existant.

## Phase 1 livree

- Entreprises corporate et contacts.
- Contrats recurrents avec prix USD, package mensuel, allowances de lavages/visites et alerte de depassement.
- Flotte client avec contrainte anti-doublon pour les plaques actives par entreprise.
- Plannings recurrents et generation idempotente d'ordres de travail.
- Ordres de travail assignes aux employes, lignes vehicules, confirmations client/associe, signatures et photos.
- Recu de service PDF authentifie.
- Roles serveur bases sur `UserProfile`: `ADMIN` et `MANAGER` gerent, `EMPLOYE` accede seulement aux ordres assignes.
- Audit via `audit.AuditLog` pour creations, changements de statut, cloture et reouverture.

## URLs principales

- `/admin-dashboard/mobile/`
- `/admin-dashboard/mobile/companies/`
- `/admin-dashboard/mobile/contracts/`
- `/admin-dashboard/mobile/schedules/`
- `/admin-dashboard/mobile/work-orders/`

## Commande de generation

```bash
venv/bin/python manage.py generate_mobile_work_orders --from 2026-10-01 --to 2026-10-31
```

La generation est sure contre les doublons grace a la contrainte `(schedule, scheduled_start)`.

## Deploiement

1. Installer les dependances existantes: `pip install -r requirements.txt`.
2. Appliquer les migrations: `python manage.py migrate`.
3. Collecter les statiques si necessaire: `python manage.py collectstatic --noinput`.
4. Redemarrer Gunicorn/service applicatif.
5. Verifier les permissions de stockage media avant usage terrain avec signatures et photos.

## Travaux restants

Phase 2: factures mensuelles, PDF facture, paiements verifies, rapprochement bancaire, depenses detaillees et rentabilite contrat.

Phase 3: pipeline leads, inventaire avance, rapports KPI, notifications et imports/exports CSV.

