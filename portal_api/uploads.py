from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from botocore.exceptions import BotoCoreError, ClientError
from functools import wraps
import logging


def handle_upload_errors(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except (BotoCoreError, ClientError, OSError):
            logging.getLogger(__name__).exception('Manager upload storage unavailable')
            return Response({'message': "Le stockage des photos est temporairement indisponible. Vos photos restent sélectionnées; réessayez dans un instant."}, status=503)
    return wrapped


def validate_photos(files):
    """Validate the entire batch before saving a wash/report or contacting storage."""
    if len(files) > 20:
        raise ValidationError({'message': 'Ajoutez au maximum 20 photos par envoi.'})
    if sum(file.size for file in files) > 40 * 1024 * 1024:
        raise ValidationError({'message': 'Les photos dépassent 40 Mo au total. Réduisez le nombre de photos.'})
    for file in files:
        if file.size > 10 * 1024 * 1024:
            raise ValidationError({'message': f'{file.name}: photo trop volumineuse (10 Mo maximum).'})
        try:
            file.seek(0)
            with Image.open(file) as image:
                if image.format not in {'JPEG', 'PNG', 'WEBP', 'GIF'}:
                    raise ValueError('format')
                if image.width * image.height > 40_000_000:
                    raise ValueError('dimensions')
                image.verify()
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            raise ValidationError({'message': f'{file.name}: photo illisible ou trop grande. Choisissez une photo JPG, PNG ou WEBP.'})
        finally:
            file.seek(0)
