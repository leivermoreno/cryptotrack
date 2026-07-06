from django.forms import DateInput, ModelForm, ValidationError
from django.utils import timezone

from .models import PortfolioTransaction


class PortfolioTransactionForm(ModelForm):
    class Meta:
        model = PortfolioTransaction
        fields = ["type", "amount", "price", "trade_date"]
        widgets = {
            "trade_date": DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # HTML5 date inputs require ISO-formatted values to parse input and to
        # render an existing value on the edit path.
        self.fields["trade_date"].input_formats = ["%Y-%m-%d"]
        # Display-only convenience field: forgiving rather than required. An
        # omitted/blank value falls back to today (see clean_trade_date), so a
        # bare buy/sell POST still works and the ledger is unaffected.
        self.fields["trade_date"].required = False
        # Default an unbound create form to today; the edit path keeps the
        # instance's stored value.
        if not self.is_bound and self.instance.pk is None:
            self.fields["trade_date"].initial = timezone.localdate()

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

    def clean_trade_date(self):
        trade_date = self.cleaned_data.get("trade_date")
        # Blank/omitted -> default to today (field is display-only, not required).
        if trade_date is None:
            return timezone.localdate()
        if trade_date > timezone.localdate():
            raise ValidationError("Trade date cannot be in the future.")
        return trade_date
