from django.forms import ModelForm, ValidationError

from .models import PortfolioTransaction


class PortfolioTransactionForm(ModelForm):
    class Meta:
        model = PortfolioTransaction
        fields = ["type", "amount", "price"]

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise ValidationError("Amount must be greater than zero.")
        return amount

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price <= 0:
            raise ValidationError("Price must be greater than zero.")
        return price
