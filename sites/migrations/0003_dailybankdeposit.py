# Generated manually

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('sites', '0002_location_gps_actif_location_latitude_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyBankDeposit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='Date du dépôt')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Montant déposé (FC)')),
                ('notes', models.TextField(blank=True, verbose_name='Notes')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Créé le')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Modifié le')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bank_deposits_created', to=settings.AUTH_USER_MODEL, verbose_name='Enregistré par')),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bank_deposits', to='sites.location', verbose_name='Site')),
            ],
            options={
                'verbose_name': 'Dépôt Bancaire Quotidien',
                'verbose_name_plural': 'Dépôts Bancaires Quotidiens',
                'ordering': ['-date', '-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='dailybankdeposit',
            index=models.Index(fields=['site', 'date'], name='sites_daily_site_id_idx'),
        ),
        migrations.AddIndex(
            model_name='dailybankdeposit',
            index=models.Index(fields=['-date'], name='sites_daily_date_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='dailybankdeposit',
            unique_together={('site', 'date')},
        ),
    ]
