from django.apps import apps
from django.core.cache import caches
from django.core.management.base import BaseCommand
from django.db.models import ImageField

from comptes.image_utils import _thumbnail_cache_key, ensure_image_thumbnail


class Command(BaseCommand):
    help = "Prepare missing photo thumbnail metadata outside web requests. Safe to repeat."

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=500)

    def handle(self, *args, **options):
        prepared = 0
        failed = 0
        for model in apps.get_models():
            if model._meta.app_label not in {'comptes', 'pointage', 'lavages', 'problemes', 'sites'}:
                continue
            for field in model._meta.fields:
                if not isinstance(field, ImageField):
                    continue
                rows = model.objects.exclude(**{field.name: ''}).exclude(
                    **{f'{field.name}__isnull': True}
                ).only('pk', field.name).iterator(chunk_size=100)
                for row in rows:
                    photo = getattr(row, field.name)
                    metadata_key = _thumbnail_cache_key(photo)
                    if caches['image_metadata'].get(metadata_key) is not None:
                        continue
                    if prepared + failed >= max(0, options['limit']):
                        self.stdout.write(f'{prepared} prepared; {failed} unavailable.')
                        return
                    try:
                        thumbnail = ensure_image_thumbnail(photo)
                    except Exception:
                        # A storage outage must not prevent later photos from being prepared.
                        thumbnail = ''
                    if thumbnail:
                        prepared += 1
                    else:
                        failed += 1
                        caches['image_metadata'].set(metadata_key, '', timeout=3600)
        self.stdout.write(f'{prepared} prepared; {failed} unavailable.')
