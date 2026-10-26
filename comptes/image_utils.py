import os
import hashlib
from datetime import datetime
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.cache import caches
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.ExifTags import TAGS


IMAGE_MAX_SIZE = (1800, 1800)
THUMBNAIL_MAX_SIZE = (520, 520)
EXIF_DATETIME_KEYS = (
    ("DateTimeOriginal", "OffsetTimeOriginal"),
    ("DateTimeDigitized", "OffsetTimeDigitized"),
    ("DateTime", ""),
)


def _get_resample_filter():
    return getattr(Image, "Resampling", Image).LANCZOS


def _seek_file(file_obj):
    if hasattr(file_obj, "seek"):
        try:
            file_obj.seek(0)
        except OSError:
            return


def _build_thumbnail_name(source_name):
    root, _ext = os.path.splitext(source_name)
    return f"{root}__thumb.webp"


def _thumbnail_cache_key(field_file):
    storage = field_file.storage
    identity = f"{storage.__class__.__module__}.{storage.__class__.__name__}:{getattr(storage, 'bucket_name', '')}:{getattr(storage, 'location', '')}:{field_file.name}"
    return hashlib.sha256(identity.encode()).hexdigest()


def remember_thumbnail(field_file, thumbnail_name):
    try:
        caches['image_metadata'].set(_thumbnail_cache_key(field_file), thumbnail_name)
    except OSError:
        pass


def _save_image_to_buffer(image, image_format, *, quality=82):
    buffer = BytesIO()
    save_kwargs = {}
    if image_format == "JPEG":
        save_kwargs.update({"quality": quality, "optimize": True, "progressive": True})
    elif image_format == "WEBP":
        save_kwargs.update({"quality": quality, "method": 6})
    elif image_format == "PNG":
        save_kwargs.update({"optimize": True})
    elif image_format == "GIF":
        save_kwargs.update({"optimize": True})
    image.save(buffer, format=image_format, **save_kwargs)
    return buffer


def _prepare_image(image):
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "RGBA", "P", "L"):
        image = image.convert("RGB")
    return image


def optimize_image_upload(field_file, *, max_size=IMAGE_MAX_SIZE):
    if not field_file or getattr(field_file, "_committed", False):
        return field_file

    _seek_file(field_file)

    try:
        with Image.open(field_file) as source_image:
            if getattr(source_image, "is_animated", False):
                _seek_file(field_file)
                return field_file

            image = _prepare_image(source_image)
            image.thumbnail(max_size, _get_resample_filter())

            source_name = getattr(field_file, "name", "image")
            extension = os.path.splitext(source_name)[1].lower()
            image_format = (source_image.format or "").upper()
            if image_format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                image_format = "PNG" if extension == ".png" else "JPEG"

            if image_format == "JPEG" and image.mode in {"RGBA", "P"}:
                image = image.convert("RGB")
            elif image_format == "GIF":
                adaptive_palette = getattr(getattr(Image, "Palette", Image), "ADAPTIVE", Image.ADAPTIVE)
                image = image.convert("P", palette=adaptive_palette)

            buffer = _save_image_to_buffer(image, image_format)
            content = ContentFile(buffer.getvalue())
            content.name = source_name
            _seek_file(field_file)
            return content
    except (OSError, UnidentifiedImageError, ValueError):
        _seek_file(field_file)
        return field_file


def ensure_image_thumbnail(field_file, *, max_size=THUMBNAIL_MAX_SIZE, force=False):
    if not field_file or not getattr(field_file, "name", ""):
        return ""

    storage = field_file.storage
    source_name = field_file.name
    thumbnail_name = _build_thumbnail_name(source_name)

    if storage.exists(thumbnail_name) and not force:
        remember_thumbnail(field_file, thumbnail_name)
        return thumbnail_name

    try:
        with storage.open(source_name, "rb") as source_handle:
            with Image.open(source_handle) as source_image:
                if getattr(source_image, "is_animated", False):
                    source_image.seek(0)

                image = _prepare_image(source_image)
                image.thumbnail(max_size, _get_resample_filter())
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGB")
                buffer = _save_image_to_buffer(image, "WEBP", quality=78)
                if storage.exists(thumbnail_name):
                    storage.delete(thumbnail_name)
                storage.save(thumbnail_name, ContentFile(buffer.getvalue()))
                remember_thumbnail(field_file, thumbnail_name)
                return thumbnail_name
    except (OSError, UnidentifiedImageError, ValueError):
        return ""


def get_thumbnail_url(field_file):
    if not field_file or not getattr(field_file, "name", ""):
        return ""

    # Rendering must never perform S3 HEAD/download requests or image processing.
    # Uploads and the maintenance command populate this shared, persistent metadata.
    try:
        thumbnail_name = caches['image_metadata'].get(_thumbnail_cache_key(field_file))
    except OSError:
        thumbnail_name = None
    if not thumbnail_name and isinstance(field_file.storage, FileSystemStorage):
        candidate = _build_thumbnail_name(field_file.name)
        if field_file.storage.exists(candidate):
            thumbnail_name = candidate
            remember_thumbnail(field_file, candidate)
    if not thumbnail_name:
        return getattr(field_file, "url", "")
    return field_file.storage.url(thumbnail_name)


def _build_exif_map(image):
    exif = image.getexif()
    if not exif:
        return {}
    return {TAGS.get(tag, tag): value for tag, value in exif.items()}



def extract_image_capture_datetime(field_file):
    if not field_file:
        return None

    _seek_file(field_file)
    try:
        with Image.open(field_file) as source_image:
            exif_map = _build_exif_map(source_image)
            if not exif_map:
                return None

            for datetime_key, offset_key in EXIF_DATETIME_KEYS:
                raw_value = str(exif_map.get(datetime_key, "")).strip()
                if not raw_value:
                    continue

                raw_offset = str(exif_map.get(offset_key, "")).strip() if offset_key else ""
                try:
                    if raw_offset:
                        parsed_value = datetime.strptime(
                            f"{raw_value}{raw_offset}",
                            "%Y:%m:%d %H:%M:%S%z",
                        )
                        return timezone.localtime(parsed_value)

                    parsed_value = datetime.strptime(raw_value, "%Y:%m:%d %H:%M:%S")
                    return timezone.make_aware(parsed_value, timezone.get_current_timezone())
                except ValueError:
                    continue
    except (OSError, UnidentifiedImageError, ValueError):
        return None
    finally:
        _seek_file(field_file)

    return None
