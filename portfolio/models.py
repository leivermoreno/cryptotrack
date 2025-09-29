from django.db import models
from django.db.models import F
from django.contrib.auth.models import User
from coins.models import Coin


class PortfolioTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    coin = models.ForeignKey(Coin, on_delete=models.CASCADE)
    type = models.CharField(max_length=4, choices=(("buy", "Buy"), ("sell", "Sell")))
    amount = models.DecimalField(max_digits=20, decimal_places=8)
    price = models.DecimalField(max_digits=20, decimal_places=8)
    created = models.DateTimeField(auto_now_add=True)
