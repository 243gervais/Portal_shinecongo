from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("problemes", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="issuereport",
            index=models.Index(
                fields=["site", "statut", "-created_at"],
                name="issue_site_statut_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="issuereport",
            index=models.Index(
                fields=["employe", "-created_at"],
                name="issue_employe_created_idx",
            ),
        ),
    ]
