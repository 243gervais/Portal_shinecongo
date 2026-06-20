from __future__ import annotations

import os
import shlex
from pathlib import Path
from fabric import Connection, task


def _env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


def _run_in_venv(conn: Connection, app_dir: str, command: str) -> None:
    conn.run(
        "bash -lc '"
        f"cd {app_dir} && "
        "source venv/bin/activate && "
        f"{command}"
        "'"
    )


def _upload_frontend_bundle(conn: Connection, app_dir: str) -> None:
    local_bundle_dir = Path(__file__).resolve().parent / "frontend_dist" / "frontend"
    remote_bundle_dir = f"{app_dir}/frontend_dist/frontend"

    conn.run(f"mkdir -p {shlex.quote(remote_bundle_dir)}")
    for asset_path in sorted(local_bundle_dir.iterdir()):
        if asset_path.is_file():
            conn.put(str(asset_path), remote=f"{remote_bundle_dir}/{asset_path.name}")


def _ensure_site_journal_reminder_cron(conn: Connection, app_dir: str) -> None:
    log_dir = f"{app_dir}/logs"
    cron_line = (
        f"* * * * * cd {shlex.quote(app_dir)} && "
        f". {shlex.quote(f'{app_dir}/venv/bin/activate')} && "
        f"python manage.py send_site_journal_reminders --quiet >> "
        f"{shlex.quote(f'{log_dir}/site_journal_reminders.log')} 2>&1"
    )

    conn.run(f"mkdir -p {shlex.quote(log_dir)}")
    conn.run(
        "(crontab -l 2>/dev/null | grep -v 'send_site_journal_reminders' || true; "
        f"echo {shlex.quote(cron_line)}) | crontab -"
    )


@task
def deploy(_c) -> None:
    """Deploy latest code to the server (git pull, migrate, collectstatic, restart)."""
    host = _env("FAB_HOST", "8.229.62.95")
    user = _env("FAB_USER", "gervaismbadu")
    app_dir = _env("FAB_PATH", "/home/gervaismbadu/portal_shinecongo")
    branch = _env("FAB_BRANCH", "main")
    key_file = _env("FAB_KEY", str(Path.home() / ".ssh" / "google_compute_engine"))
    service = _env("FAB_SERVICE", "portal-shinecongo")

    connect_kwargs = {}
    if key_file:
        connect_kwargs["key_filename"] = key_file

    conn = Connection(host=host, user=user, connect_kwargs=connect_kwargs)

    with conn.cd(app_dir):
        conn.run(f"git pull origin {branch}")

    _upload_frontend_bundle(conn, app_dir)
    _run_in_venv(conn, app_dir, "pip install -r requirements.txt")
    _run_in_venv(conn, app_dir, "python manage.py migrate --noinput")
    _run_in_venv(conn, app_dir, "python manage.py collectstatic --noinput")
    _ensure_site_journal_reminder_cron(conn, app_dir)

    conn.sudo(f"systemctl restart {service}")
