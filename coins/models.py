from django.db import models
from django.contrib.auth.models import User


class Coin(models.Model):
    cg_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    symbol = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)


class Watchlist(models.Model):
    coin = models.ForeignKey(Coin, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    @staticmethod
    def get_coin_ids_for_user(user_id):
        return Watchlist.objects.filter(
            user_id=user_id, coin__is_active=True
        ).values_list("coin__cg_id", flat=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["coin_id", "user_id"], name="unique_watchlist"
            )
        ]
