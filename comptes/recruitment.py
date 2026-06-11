from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from dotenv import dotenv_values


logger = logging.getLogger(__name__)

DEFAULT_RECRUITMENT_ENV_PATH = "/home/gervaismbadu/shinecongo.env"
DEFAULT_RECRUITMENT_MEDIA_BASE_URL = "https://shinecongo.org/media/"
DEFAULT_RECRUITMENT_SQL_DUMP_PATH = "/home/gervaismbadu/shinecongo-db.sql"

SQL_DUMP_APPLICATION_FIELDS = [
    "id",
    "full_name",
    "phone",
    "city",
    "message",
    "cv_file",
    "applied_at",
    "reviewed",
    "notes",
    "date_of_birth",
    "physical_address",
    "application_type",
    "education",
    "how_heard_about",
    "how_heard_details",
    "languages",
    "lieu_de_naissance",
    "nationalite",
    "nom",
    "post_nom",
    "prenom",
    "sexe",
    "skills",
]


@dataclass(frozen=True)
class ReviewedCandidateCV:
    external_id: str
    full_name: str
    phone: str
    city: str
    applied_at: datetime | None
    cv_file: str
    cv_url: str

    @property
    def label(self) -> str:
        details = [self.full_name]
        if self.phone:
            details.append(self.phone)
        if self.applied_at:
            details.append(self.applied_at.strftime("%d/%m/%Y"))
        return " • ".join(details)


def _clean_value(value: Any) -> str:
    if value is None:
        return ""
    normalized = str(value).strip()
    if normalized == "\\N":
        return ""
    return normalized


def _get_candidate_name(row: dict[str, Any]) -> str:
    direct_name = _clean_value(row.get("full_name"))
    if direct_name:
        return direct_name

    name_parts = [
        _clean_value(row.get("prenom")),
        _clean_value(row.get("nom")),
        _clean_value(row.get("post_nom")),
    ]
    resolved_name = " ".join(part for part in name_parts if part).strip()
    return resolved_name or f"Candidat #{row.get('id')}"


def _parse_applied_at(value: Any) -> datetime | None:
    raw_value = _clean_value(value)
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        return None


def _load_external_env_values() -> dict[str, str]:
    explicit_path = os.getenv("SHINECONGO_RECRUITMENT_ENV_FILE")
    env_paths = [path for path in [explicit_path, DEFAULT_RECRUITMENT_ENV_PATH] if path]

    for env_path in env_paths:
        path = Path(env_path)
        if not path.exists():
            continue
        values = dotenv_values(path)
        return {key: str(value) for key, value in values.items() if value is not None}
    return {}


def get_recruitment_database_url() -> str:
    return os.getenv("SHINECONGO_RECRUITMENT_DATABASE_URL") or _load_external_env_values().get("DATABASE_URL", "")


def get_recruitment_media_base_url() -> str:
    return (
        os.getenv("SHINECONGO_RECRUITMENT_MEDIA_BASE_URL")
        or _load_external_env_values().get("MEDIA_URL", "")
        or DEFAULT_RECRUITMENT_MEDIA_BASE_URL
    )


def get_recruitment_sql_dump_path() -> str:
    return os.getenv("SHINECONGO_RECRUITMENT_SQL_DUMP_PATH", DEFAULT_RECRUITMENT_SQL_DUMP_PATH)


def build_recruitment_cv_url(cv_file: str) -> str:
    normalized_cv_file = _clean_value(cv_file).lstrip("/")
    if not normalized_cv_file:
        return ""
    if normalized_cv_file.startswith(("http://", "https://")):
        return normalized_cv_file
    if normalized_cv_file.startswith("media/"):
        normalized_cv_file = normalized_cv_file[6:]
    return urljoin(get_recruitment_media_base_url(), quote(normalized_cv_file, safe="/"))


def _build_reviewed_candidate(row: dict[str, Any]) -> ReviewedCandidateCV | None:
    reviewed_value = _clean_value(row.get("reviewed")).lower()
    if reviewed_value not in {"true", "t", "1"}:
        return None

    cv_file = _clean_value(row.get("cv_file"))
    if not cv_file:
        return None

    cv_url = build_recruitment_cv_url(cv_file)
    if not cv_url:
        return None

    return ReviewedCandidateCV(
        external_id=str(row.get("id", "")).strip(),
        full_name=_get_candidate_name(row),
        phone=_clean_value(row.get("phone")),
        city=_clean_value(row.get("city")),
        applied_at=_parse_applied_at(row.get("applied_at")),
        cv_file=cv_file,
        cv_url=cv_url,
    )


def _load_reviewed_candidates_from_postgres(limit: int) -> list[ReviewedCandidateCV]:
    database_url = get_recruitment_database_url()
    if not database_url:
        return []

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        return []

    with psycopg.connect(database_url) as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    full_name,
                    phone,
                    city,
                    cv_file,
                    applied_at,
                    reviewed,
                    nom,
                    post_nom,
                    prenom
                FROM applications_jobapplication
                WHERE reviewed = TRUE
                ORDER BY applied_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()

    reviewed_candidates: list[ReviewedCandidateCV] = []
    for row in rows:
        candidate = _build_reviewed_candidate(row)
        if candidate:
            reviewed_candidates.append(candidate)
    return reviewed_candidates


def _load_reviewed_candidates_from_sql_dump(limit: int) -> list[ReviewedCandidateCV]:
    sql_dump_path = Path(get_recruitment_sql_dump_path())
    if not sql_dump_path.exists():
        return []

    dump_text = sql_dump_path.read_text(errors="ignore")
    copy_marker = "COPY public.applications_jobapplication "
    marker_index = dump_text.find(copy_marker)
    if marker_index < 0:
        return []

    block_start = dump_text.find("\n", marker_index)
    if block_start < 0:
        return []
    block_start += 1

    block_end = dump_text.find("\n\\.\n", block_start)
    if block_end < 0:
        return []

    reviewed_candidates: list[ReviewedCandidateCV] = []
    for row_text in dump_text[block_start:block_end].splitlines():
        if not row_text.strip():
            continue
        values = row_text.split("\t")
        if len(values) < len(SQL_DUMP_APPLICATION_FIELDS):
            continue
        row = dict(zip(SQL_DUMP_APPLICATION_FIELDS, values))
        candidate = _build_reviewed_candidate(row)
        if candidate:
            reviewed_candidates.append(candidate)
        if len(reviewed_candidates) >= limit:
            break

    reviewed_candidates.sort(
        key=lambda item: item.applied_at.timestamp() if item.applied_at else float("-inf"),
        reverse=True,
    )
    return reviewed_candidates


def get_reviewed_candidate_cv_choices(limit: int = 100) -> list[ReviewedCandidateCV]:
    try:
        reviewed_candidates = _load_reviewed_candidates_from_postgres(limit)
        if reviewed_candidates:
            return reviewed_candidates
    except Exception:
        logger.exception("Impossible de charger les CV validés depuis la base recrutement Shine Congo.")

    try:
        return _load_reviewed_candidates_from_sql_dump(limit)
    except Exception:
        logger.exception("Impossible de charger les CV validés depuis le dump recrutement Shine Congo.")
        return []
