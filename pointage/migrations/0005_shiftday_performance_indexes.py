from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pointage", "0004_shiftday_daily_expenses_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="shiftday",
            index=models.Index(
                fields=["site", "date", "daily_report_confirmed"],
                name="pointage_site_date_report_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="shiftday",
            index=models.Index(
                fields=["employe", "-updated_at"],
                name="pointage_employe_updated_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="shiftday",
            index=models.Index(
                fields=["-created_at"],
                name="pointage_created_desc_idx",
            ),
        ),
    ]
