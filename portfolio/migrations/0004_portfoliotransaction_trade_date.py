# Hand-split from the default makemigrations output (step 11.7, Option B).
#
# makemigrations collapses this into a single AddField with the localdate
# default, which would stamp every *existing* row with TODAY and destroy the
# historical (created, id) FIFO ordering that build_holdings / portfolio.ledger
# depend on. Instead we:
#   (a) add the column nullable with no default,
#   (b) backfill trade_date from the DATE of each row's `created`, and
#   (c) alter to non-null with the localdate default for new rows.
# trade_date is display-only; the ledger still orders by (created, id).
import django.utils.timezone
from django.db import migrations, models


def backfill_trade_date_from_created(apps, schema_editor):
    PortfolioTransaction = apps.get_model("portfolio", "PortfolioTransaction")
    # created is timezone-aware (USE_TZ=True); use the local date so trade_date
    # matches how `created` is rendered in the UI.
    for tx in PortfolioTransaction.objects.all().iterator():
        tx.trade_date = django.utils.timezone.localtime(tx.created).date()
        tx.save(update_fields=["trade_date"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("portfolio", "0003_alter_portfoliotransaction_amount_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="portfoliotransaction",
            name="trade_date",
            field=models.DateField(null=True),
        ),
        migrations.RunPython(backfill_trade_date_from_created, noop),
        migrations.AlterField(
            model_name="portfoliotransaction",
            name="trade_date",
            field=models.DateField(default=django.utils.timezone.localdate),
        ),
    ]
