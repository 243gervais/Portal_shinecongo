import os

from django.core.exceptions import ValidationError


ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_DOCUMENT_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | {".pdf"}
MAX_UPLOAD_SIZE = 8 * 1024 * 1024


def validate_mobile_file(uploaded_file):
    extension = os.path.splitext(uploaded_file.name or "")[1].lower()
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValidationError("Format non supporte. Utilisez JPG, PNG, WEBP ou PDF.")
    if uploaded_file.size and uploaded_file.size > MAX_UPLOAD_SIZE:
        raise ValidationError("Le fichier depasse la limite de 8 MB.")
    return uploaded_file


def validate_mobile_image(uploaded_file):
    extension = os.path.splitext(uploaded_file.name or "")[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError("Format image non supporte. Utilisez JPG, PNG ou WEBP.")
    if uploaded_file.size and uploaded_file.size > MAX_UPLOAD_SIZE:
        raise ValidationError("L'image depasse la limite de 8 MB.")
    return uploaded_file

