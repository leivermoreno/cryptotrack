from django.conf import settings
from django.db import models


class Coin(models.Model):
    cg_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    symbol = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Watchlist(models.Model):
    coin = models.ForeignKey(Coin, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def get_coin_ids_for_user(user_id):
        return (
            Watchlist.objects.filter(user_id=user_id, coin__is_active=True)
            .order_by("created", "id")
            .values_list("coin__cg_id", flat=True)
        )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["coin_id", "user_id"], name="unique_watchlist"
            )
        ]
