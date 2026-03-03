from __future__ import annotations

import os
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

    _run_in_venv(conn, app_dir, "pip install -r requirements.txt")
    _run_in_venv(conn, app_dir, "python manage.py migrate --noinput")
    _run_in_venv(conn, app_dir, "python manage.py collectstatic --noinput")

    conn.sudo(f"systemctl restart {service}")
