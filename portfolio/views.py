from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.urls import reverse

from .models import PortfolioTransaction
from .forms import PortfolioTransactionForm
from coins.models import Coin
from portfolio.utils import get_coin_balance


@login_required()
def create_portfolio_transaction(request, coin_id, transaction_id=None):
    try:
        coin = Coin.objects.get(id=coin_id)
        transactions = PortfolioTransaction.get_for_user_and_coin(request.user, coin)
        balance = get_coin_balance(transactions)
        transaction = None
        if transaction_id:
            transaction = transactions.get(id=transaction_id)
    except (Coin.DoesNotExist, PortfolioTransaction.DoesNotExist):
        return redirect(reverse("coins:watchlist"))

    form = PortfolioTransactionForm(request.POST or None, instance=transaction)
    if request.method == "POST":
        if form.is_valid():
            if (
                form.cleaned_data["transaction_type"] == "sell"
                and form.cleaned_data["amount"] > balance
            ):
                form.add_error("amount", "Insufficient balance to sell this amount.")
            else:
                transaction = form.save(commit=False)
                transaction.user = request.user
                transaction.coin = coin
                transaction.save()
                return redirect("portfolio:add_transaction", coin_id=coin_id)

    return render(
        request,
        "portfolio/create_transaction.html",
        {
            "form": form,
            "coin": coin,
            "balance": balance,
            "transaction": transaction_id,
            "transactions": transactions,
        },
    )
