from django.forms import ModelForm
from .models import PortfolioTransaction


class PortfolioTransactionForm(ModelForm):
    class Meta:
        model = PortfolioTransaction
        fields = ["type", "amount", "price"]
