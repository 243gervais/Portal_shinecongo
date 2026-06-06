from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lavages", "0003_carwash_is_system_generated_carwash_system_source_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="carwash",
            index=models.Index(
                fields=["employe", "-created_at"],
                name="lavages_employe_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="carwash",
            index=models.Index(
                fields=["site", "-created_at"],
                name="lavages_site_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="carwashphoto",
            index=models.Index(
                fields=["lavage", "-uploaded_at"],
                name="lavage_photo_uploaded_idx",
            ),
        ),
    ]
