from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Case, F, Q, Sum, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from coins.models import Coin


class PortfolioTransaction(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    coin = models.ForeignKey(Coin, on_delete=models.CASCADE)
    type = models.CharField(max_length=4, choices=(("buy", "Buy"), ("sell", "Sell")))
    amount = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        validators=[MinValueValidator(Decimal("0.00000001"))],
    )
    price = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        validators=[MinValueValidator(Decimal("0.00000001"))],
    )
    created = models.DateTimeField(auto_now_add=True)
    # User-entered trade date (date-only). Distinct from the auto `created`
    # insert timestamp: `trade_date` is the authoritative FIFO/ledger order key,
    # while `created` remains audit metadata. Defaults to today for new rows;
    # existing rows were backfilled from the date of `created`.
    trade_date = models.DateField(default=timezone.localdate)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="portfolio_transaction_amount_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(price__gt=0),
                name="portfolio_transaction_price_gt_0",
            ),
        ]
        indexes = [
            # Workhorse composite: equality on (user, coin) then the FIFO keys.
            # Serves the ledger FOR UPDATE lock path (portfolio.ledger._locked_rows),
            # build_holdings (user + coin_id__in), and per-coin transaction lists
            # via the (user, coin) prefix.
            models.Index(
                fields=["user", "coin", "trade_date", "id"],
                name="pf_txn_user_coin_trade_date_id",
            ),
            # Default ordering of the transaction lists.
            models.Index(
                fields=["user", "trade_date"],
                name="pf_txn_user_trade_date",
            ),
        ]

    @staticmethod
    def get_for_user(user):
        return (
            PortfolioTransaction.objects.filter(user=user)
            .annotate(
                total=F("amount") * F("price"),
            )
            .select_related("coin")
        )

    @staticmethod
    def get_coin_balance(user, coin):
        balance = PortfolioTransaction.objects.filter(user=user, coin=coin).aggregate(
            amount_sum=Coalesce(
                Sum(
                    Case(
                        When(type="buy", then="amount"),
                        When(type="sell", then=-F("amount")),
                        default=Decimal("0"),
                    )
                ),
                Decimal("0"),
            )
        )["amount_sum"]
        return balance

    @staticmethod
    def get_positive_coin_balance_ids(user):
        return (
            PortfolioTransaction.objects.filter(user=user)
            .values(
                "coin",
            )
            .annotate(
                balance=Sum(
                    Case(
                        When(type="buy", then="amount"),
                        When(type="sell", then=-F("amount")),
                        default=Decimal(0),
                    )
                )
            )
            .filter(balance__gt=0)
            .values("coin_id", "coin__cg_id")
        )
