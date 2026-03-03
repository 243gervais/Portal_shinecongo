# Generated manually

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import sites.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('sites', '0004_rename_sites_daily_site_id_idx_sites_daily_site_id_267216_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_type', models.CharField(choices=[('CONTRAT', 'Contrat avec le prêteur'), ('PAIEMENT', 'Paiement de location'), ('COMPTE_BANCAIRE', 'Photo compte bancaire du prêteur'), ('PHOTO_CONSTRUCTION', 'Photo de construction'), ('VIDEO_CONSTRUCTION', 'Vidéo de construction'), ('AUTRE_DOCUMENT', 'Autre document'), ('AUTRE_PHOTO', 'Autre photo'), ('AUTRE_VIDEO', 'Autre vidéo')], default='AUTRE_DOCUMENT', max_length=30, verbose_name='Type de fichier')),
                ('title', models.CharField(max_length=200, verbose_name='Titre')),
                ('description', models.TextField(blank=True, verbose_name='Description')),
                ('file', models.FileField(upload_to=sites.models.site_document_path, verbose_name='Fichier')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True, verbose_name='Uploadé le')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Modifié le')),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='sites.location', verbose_name='Site')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='site_documents_uploaded', to=settings.AUTH_USER_MODEL, verbose_name='Uploadé par')),
            ],
            options={
                'verbose_name': 'Document du Site',
                'verbose_name_plural': 'Documents du Site',
                'ordering': ['-uploaded_at'],
            },
        ),
        migrations.AddIndex(
            model_name='sitedocument',
            index=models.Index(fields=['site', 'file_type'], name='sites_sited_site_id_idx'),
        ),
        migrations.AddIndex(
            model_name='sitedocument',
            index=models.Index(fields=['-uploaded_at'], name='sites_sited_uploaded_idx'),
        ),
    ]
