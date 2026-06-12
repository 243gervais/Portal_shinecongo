from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from dotenv import dotenv_values
from django.core.files.base import ContentFile
from django.utils.text import slugify
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


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
    reviewed: bool
    cv_file: str
    cv_url: str
    physical_address: str = ""
    date_of_birth: str = ""
    education: str = ""
    skills: str = ""
    message: str = ""
    notes: str = ""
    application_type: str = ""
    how_heard_about: str = ""
    languages: str = ""
    nationalite: str = ""

    @property
    def label(self) -> str:
        details = [self.full_name]
        if self.phone:
            details.append(self.phone)
        if self.applied_at:
            details.append(self.applied_at.strftime("%d/%m/%Y"))
        details.append("Revu" if self.reviewed else "À revoir")
        details.append("CV joint" if self.has_uploaded_cv else "Dossier généré")
        return " • ".join(details)

    @property
    def has_uploaded_cv(self) -> bool:
        return bool(self.cv_url)


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
    is_reviewed = reviewed_value in {"true", "t", "1"}

    cv_file = _clean_value(row.get("cv_file"))
    cv_url = build_recruitment_cv_url(cv_file)

    return ReviewedCandidateCV(
        external_id=str(row.get("id", "")).strip(),
        full_name=_get_candidate_name(row),
        phone=_clean_value(row.get("phone")),
        city=_clean_value(row.get("city")),
        applied_at=_parse_applied_at(row.get("applied_at")),
        reviewed=is_reviewed,
        cv_file=cv_file,
        cv_url=cv_url,
        physical_address=_clean_value(row.get("physical_address")),
        date_of_birth=_clean_value(row.get("date_of_birth")),
        education=_clean_value(row.get("education")),
        skills=_clean_value(row.get("skills")),
        message=_clean_value(row.get("message")),
        notes=_clean_value(row.get("notes")),
        application_type=_clean_value(row.get("application_type")),
        how_heard_about=_clean_value(row.get("how_heard_about")),
        languages=_clean_value(row.get("languages")),
        nationalite=_clean_value(row.get("nationalite")),
    )


def _wrap_pdf_text(value: str, font_name: str, font_size: int, max_width: float) -> list[str]:
    words = (value or "").split()
    if not words:
        return []

    lines: list[str] = []
    current_line = words[0]
    for word in words[1:]:
        candidate = f"{current_line} {word}"
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current_line = candidate
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines


def build_candidate_dossier_pdf(candidate: ReviewedCandidateCV) -> ContentFile:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_width, page_height = A4
    left_margin = 50
    right_margin = 50
    current_y = page_height - 60
    line_height = 16
    max_width = page_width - left_margin - right_margin

    def write_line(text: str, font_name: str = "Helvetica", font_size: int = 11, gap: int | None = None) -> None:
        nonlocal current_y
        for wrapped_line in _wrap_pdf_text(text, font_name, font_size, max_width) or [""]:
            if current_y <= 60:
                pdf.showPage()
                current_y = page_height - 60
            pdf.setFont(font_name, font_size)
            pdf.drawString(left_margin, current_y, wrapped_line)
            current_y -= gap or line_height

    pdf.setTitle(f"Dossier candidature - {candidate.full_name}")
    write_line("Dossier candidature Shine Congo", "Helvetica-Bold", 16, 22)
    write_line(f"Nom: {candidate.full_name}", "Helvetica-Bold")
    write_line(f"Téléphone: {candidate.phone or '-'}")
    write_line(f"Ville: {candidate.city or '-'}")
    write_line(f"Adresse: {candidate.physical_address or '-'}")
    write_line(f"Date de naissance: {candidate.date_of_birth or '-'}")
    write_line(f"Nationalité: {candidate.nationalite or '-'}")
    write_line(f"Langues: {candidate.languages or '-'}")
    write_line(f"Type de candidature: {candidate.application_type or '-'}")
    write_line(f"Statut admin: {'Revu' if candidate.reviewed else 'À revoir'}")
    if candidate.applied_at:
        write_line(f"Date d'enregistrement: {candidate.applied_at.strftime('%d/%m/%Y %H:%M')}")
    write_line("")

    sections = [
        ("Formation", candidate.education),
        ("Compétences", candidate.skills),
        ("Comment il a connu Shine Congo", candidate.how_heard_about),
        ("Message candidat", candidate.message),
        ("Notes admin", candidate.notes),
    ]
    for title, content in sections:
        if not content:
            continue
        write_line(title, "Helvetica-Bold", 12, 18)
        write_line(content)
        write_line("")

    pdf.save()
    buffer.seek(0)
    filename = f"{slugify(candidate.full_name) or 'candidat'}-dossier-candidature.pdf"
    return ContentFile(buffer.read(), name=filename)


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
                    message,
                    notes,
                    physical_address,
                    date_of_birth,
                    education,
                    how_heard_about,
                    languages,
                    nationalite,
                    application_type,
                    skills,
                    nom,
                    post_nom,
                    prenom
                FROM applications_jobapplication
                ORDER BY reviewed DESC, applied_at DESC
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
        key=lambda item: (
            1 if item.reviewed else 0,
            item.applied_at.timestamp() if item.applied_at else float("-inf"),
        ),
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
