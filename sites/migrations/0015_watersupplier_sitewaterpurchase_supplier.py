from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import sites.models
from django.db import migrations, models


def seed_default_water_supplier(apps, schema_editor):
    WaterSupplier = apps.get_model("sites", "WaterSupplier")
    SiteWaterPurchase = apps.get_model("sites", "SiteWaterPurchase")

    default_supplier, _ = WaterSupplier.objects.get_or_create(
        name="Honosha's Forage",
        defaults={
            "price_per_tank_fc": Decimal("22000"),
            "is_active": True,
            "is_default": True,
        },
    )
    default_supplier.price_per_tank_fc = Decimal("22000")
    default_supplier.is_active = True
    default_supplier.is_default = True
    default_supplier.save(update_fields=["price_per_tank_fc", "is_active", "is_default", "updated_at"])

    WaterSupplier.objects.exclude(pk=default_supplier.pk).filter(is_default=True).update(is_default=False)
    SiteWaterPurchase.objects.filter(supplier__isnull=True).update(supplier=default_supplier)


class Migration(migrations.Migration):

    dependencies = [
        ("sites", "0014_dailycamerareport_final_three_wheelers_count_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="WaterSupplier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, unique=True, verbose_name="Nom")),
                (
                    "price_per_tank_fc",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("22000"),
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Prix par remplissage (FC)",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="Actif")),
                ("is_default", models.BooleanField(default=False, verbose_name="Fournisseur par défaut")),
                ("notes", models.TextField(blank=True, verbose_name="Notes")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Créé le")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Modifié le")),
            ],
            options={
                "verbose_name": "Fournisseur d'eau",
                "verbose_name_plural": "Fournisseurs d'eau",
                "ordering": ["-is_default", "name"],
            },
        ),
        migrations.AddField(
            model_name="sitewaterpurchase",
            name="supplier",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="water_purchases",
                to="sites.watersupplier",
                verbose_name="Fournisseur / forage",
            ),
        ),
        migrations.RunPython(seed_default_water_supplier, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="sitewaterpurchase",
            name="supplier",
            field=models.ForeignKey(
                default=sites.models.get_default_water_supplier_pk,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="water_purchases",
                to="sites.watersupplier",
                verbose_name="Fournisseur / forage",
            ),
        ),
    ]
