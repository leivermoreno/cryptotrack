from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, redirect

from coins.models import Coin
from common.decorators.views import validate_common_params
from common.utils import get_common_params, add_direction_sign
from portfolio.forms import PortfolioTransactionForm
from portfolio.models import PortfolioTransaction
from portfolio.settings import ALLOWED_SORTS, DEFAULT_SORT, DEFAULT_DIRECTION
from portfolio.utils import get_coin_balance

validate_common_params = validate_common_params(ALLOWED_SORTS)
get_common_params = get_common_params(DEFAULT_SORT, DEFAULT_DIRECTION)


@login_required()
@validate_common_params
def create_portfolio_transaction(request, coin_id, transaction_id=None):
    try:
        coin = Coin.objects.get(id=coin_id)
        transactions = PortfolioTransaction.get_for_user_and_coin(request.user, coin)
        page, sort, direction = get_common_params(request, page_count=len(transactions))
        transactions = transactions.order_by(add_direction_sign(sort, direction))
        page = Paginator(transactions, 10).page(page)
        balance = get_coin_balance(transactions)
        transaction = None
        if transaction_id:
            transaction = transactions.get(id=transaction_id)
    except (Coin.DoesNotExist, PortfolioTransaction.DoesNotExist):
        return redirect("coins:watchlist")

    form = PortfolioTransactionForm(request.POST or None, instance=transaction)
    if request.method == "POST":
        if form.is_valid():
            if (
                form.cleaned_data["type"] == "sell"
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
            "page": page,
            "sort": sort,
            "direction": direction,
        },
    )
