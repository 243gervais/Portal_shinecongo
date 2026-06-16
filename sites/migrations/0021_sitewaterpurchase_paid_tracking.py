from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sites", "0020_sitewaterpurchase_reporting_week_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitewaterpurchase",
            name="paid_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Payé le"),
        ),
        migrations.AddField(
            model_name="sitewaterpurchase",
            name="paid_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="site_water_purchases_paid",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Payé par",
            ),
        ),
        migrations.AddIndex(
            model_name="sitewaterpurchase",
            index=models.Index(
                fields=["billing_month", "supplier", "paid_at"],
                name="sites_sw_bill_sup_paid_idx",
            ),
        ),
    ]
