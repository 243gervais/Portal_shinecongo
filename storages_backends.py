"""
Storage backends for AWS S3
This module will only work if django-storages and boto3 are installed.
"""
try:
    from storages.backends.s3boto3 import S3Boto3Storage
    from botocore.config import Config
    
    class StaticStorage(S3Boto3Storage):
        """Storage for static files (CSS, JS, etc.)"""
        location = 'static'
        default_acl = 'public-read'
    
    
    class MediaStorage(S3Boto3Storage):
        """Storage for media files (user uploads, photos)"""
        location = 'media'
        default_acl = 'public-read'
        file_overwrite = False
        # Do not let a stalled storage connection occupy a web worker indefinitely.
        client_config = Config(connect_timeout=5, read_timeout=10, retries={'mode': 'standard', 'total_max_attempts': 2})

except ImportError:
    # If storages is not installed, these classes won't be available
    # This is fine - the settings.py will handle the fallback
    pass
