import os
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError


IMAGE_MAX_SIZE = (1800, 1800)
THUMBNAIL_MAX_SIZE = (520, 520)


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
                return thumbnail_name
    except (OSError, UnidentifiedImageError, ValueError):
        return ""


def get_thumbnail_url(field_file):
    if not field_file or not getattr(field_file, "name", ""):
        return ""

    thumbnail_name = ensure_image_thumbnail(field_file)
    if not thumbnail_name:
        return getattr(field_file, "url", "")
    return field_file.storage.url(thumbnail_name)
