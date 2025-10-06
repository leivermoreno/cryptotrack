from decimal import Decimal

from django.db import models
from django.db.models import F, Case, When, Sum
from django.contrib.auth.models import User
from coins.models import Coin


class PortfolioTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    coin = models.ForeignKey(Coin, on_delete=models.CASCADE)
    type = models.CharField(max_length=4, choices=(("buy", "Buy"), ("sell", "Sell")))
    amount = models.DecimalField(max_digits=20, decimal_places=8)
    price = models.DecimalField(max_digits=20, decimal_places=8)
    created = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def get_for_user(user):
        return (
            PortfolioTransaction.objects.filter(user=user, coin__is_active=True)
            .annotate(
                total=F("amount") * F("price"),
            )
            .select_related("coin")
        )

    @staticmethod
    def get_coin_balance(user, coin):
        balance = PortfolioTransaction.objects.filter(
            user=user, coin=coin, coin__is_active=True
        ).aggregate(
            amount_sum=Sum(
                Case(
                    When(type="buy", then="amount"),
                    When(type="sell", then=-F("amount")),
                    default=Decimal("0"),
                )
            )
        )[
            "amount_sum"
        ]
        return balance

    @staticmethod
    def get_positive_coin_balance_ids(user):
        return (
            PortfolioTransaction.objects.filter(user=user, coin__is_active=True)
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
