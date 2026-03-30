from django.db import migrations, models
import django.utils.timezone


def initialize_admin_inbox_seen(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('comptes', 'UserProfile')
    now = django.utils.timezone.now()

    UserProfile.objects.filter(role='ADMIN').update(
        admin_requests_last_seen_at=now,
        admin_reports_last_seen_at=now,
    )

    superuser_ids = User.objects.filter(is_superuser=True).values_list('id', flat=True)
    UserProfile.objects.filter(user_id__in=superuser_ids).update(
        role='ADMIN',
        admin_requests_last_seen_at=now,
        admin_reports_last_seen_at=now,
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('comptes', '0006_userprofile_profile_photo'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='admin_reports_last_seen_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Dernière consultation des rapports admin'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='admin_requests_last_seen_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Dernière consultation des demandes admin'),
        ),
        migrations.RunPython(initialize_admin_inbox_seen, noop_reverse),
    ]
