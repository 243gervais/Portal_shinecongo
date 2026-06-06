from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("comptes", "0010_alter_userprofile_role"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="userprofile",
            index=models.Index(
                fields=["site", "role", "actif"],
                name="cp_prof_site_role_actif_ix",
            ),
        ),
        migrations.AddIndex(
            model_name="userprofile",
            index=models.Index(
                fields=["role", "actif"],
                name="cp_prof_role_actif_ix",
            ),
        ),
        migrations.AddIndex(
            model_name="userprofile",
            index=models.Index(
                fields=["-created_at"],
                name="cp_prof_created_desc_ix",
            ),
        ),
    ]
