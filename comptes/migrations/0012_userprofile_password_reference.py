from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("comptes", "0011_userprofile_performance_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="password_reference",
            field=models.CharField(
                blank=True,
                help_text="Référence visible uniquement dans la page admin Gestion des mots de passe.",
                max_length=255,
                verbose_name="Mot de passe mémorisé",
            ),
        ),
    ]
