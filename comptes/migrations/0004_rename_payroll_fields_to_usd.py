from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("comptes", "0003_alter_employeepayment_amount_paid_fc_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="userprofile",
            old_name="salaire_mensuel_fc",
            new_name="salaire_mensuel_usd",
        ),
        migrations.RenameField(
            model_name="employeepayment",
            old_name="salary_base_fc",
            new_name="salary_base_usd",
        ),
        migrations.RenameField(
            model_name="employeepayment",
            old_name="amount_paid_fc",
            new_name="amount_paid_usd",
        ),
    ]
