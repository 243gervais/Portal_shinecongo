# Shine Congo Portal SPA And Performance Notes

## Current Architecture

- Django remains the backend for authentication, permissions, models, business rules, uploads, admin pages, and public/camera pages.
- The authenticated employee and manager portals are served by `templates/portal/spa.html`.
- Django routes under `/employe/` and `/manager/` return the same React shell for normal `GET` requests, so refreshing nested portal URLs loads React instead of a 404.
- React Router controls navigation inside the employee and manager portals.
- Django REST Framework endpoints under `/api/portal/` return JSON to the React portal.
- The custom admin dashboard, Django admin, camera pages, auth routes, static files, and media files remain server-rendered or directly served.

## Routing Boundaries

React owns:

- `/employe/`
- `/employe/pointage/`
- `/employe/lavage/ajouter/`
- `/employe/lavage/mes-lavages/`
- `/employe/lavage/<id>/`
- `/employe/probleme/signaler/`
- `/employe/probleme/mes-problemes/`
- `/employe/probleme/<id>/`
- `/employe/rapport-journee/`
- `/employe/eau/`
- `/employe/carburant/`
- `/employe/historique/`
- `/manager/`
- `/manager/pointages/`
- `/manager/pointages/<id>/corriger/`
- `/manager/lavages/`
- `/manager/problemes/`
- `/manager/qr/<site_id>/`

Django still owns:

- `/api/`
- `/admin/`
- `/admin-dashboard/`
- `/login/`
- `/logout/`
- `/register/`
- `/static/`
- `/media/`
- camera/public pages

## Navigation

The portal layout is a persistent React Router layout with sidebar/header navigation and an `<Outlet />`.
Internal portal links use `Link` or `NavLink`.
Logout, uploaded media, downloads, admin pages, and camera/public pages intentionally remain normal browser links.

## Authentication And CSRF

The portal continues to use Django session authentication.
The shared React API client sends `credentials: "same-origin"` and includes the `csrftoken` cookie on unsafe methods.
Do not move session credentials into `localStorage`.

## Performance Changes

- Route-level lazy loading splits employee and manager pages out of the initial React bundle.
- The shared API client supports `AbortSignal` so route changes can cancel stale requests.
- Employee and manager list APIs are paginated.
- Manager lavage totals now use one aggregate query for count and amount.
- Manager dashboard API responses are cached for 45 seconds per user and date range. This is a short TTL cache for repeated dashboard navigation; it may show operational changes up to 45 seconds late.

## Static Assets

Production deploys should run:

```bash
cd frontend
npm ci
npm run build
cd ..
python manage.py collectstatic --noinput
```

Nginx should serve `/static/` and `/media/` directly. Gunicorn should only serve Django requests.

## Deployment

Existing AWS/Lightsail-style deployment sequence:

```bash
git pull origin main
source /home/ubuntu/portal_shinecongo/venv/bin/activate
pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py check --deploy
sudo nginx -t
sudo systemctl restart shinecongo
sudo systemctl reload nginx
```

## Rollback

```bash
git log --oneline -5
git checkout <previous_good_commit>
source /home/ubuntu/portal_shinecongo/venv/bin/activate
pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
python manage.py migrate --noinput
python manage.py collectstatic --noinput
sudo systemctl restart shinecongo
sudo systemctl reload nginx
```

If a migration from a future change must be rolled back, inspect it first and run the targeted app migration back to the previous migration.

## Follow-Up Risks

- The custom `/admin-dashboard/` area remains Django-rendered and can still perform full page navigations.
- Manager/admin reporting pages contain heavier finance and history calculations than the employee/manager React portal APIs.
- Production instance CPU, memory, and live PostgreSQL query plans are not present in this repository, so worker counts and database index recommendations should be verified on the server before tuning further.
