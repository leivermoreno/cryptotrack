from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from coins.models import Coin
from common.decorators.views import validate_common_params
from common.utils import get_common_params, add_direction_sign
from portfolio.forms import PortfolioTransactionForm
from portfolio.models import PortfolioTransaction
from portfolio.services import get_portfolio_overview_data
from portfolio.settings import (
    ALLOWED_SORTS,
    DEFAULT_SORT,
    DEFAULT_DIRECTION,
    TRANSACTIONS_PER_PAGE,
)

validate_common_params_defaults = validate_common_params(ALLOWED_SORTS)
get_common_params_defaults = get_common_params(DEFAULT_SORT, DEFAULT_DIRECTION)


@login_required
@validate_common_params
def portfolio_overview(request):
    positive_balance_coin_ids = PortfolioTransaction.get_positive_coin_balance_ids(
        user=request.user
    )
    cg_to_db_id_map = {
        item["coin__cg_id"]: item["coin_id"] for item in positive_balance_coin_ids
    }

    portfolio_overview_data = get_portfolio_overview_data(
        user=request.user, cg_to_db_id_map=cg_to_db_id_map
    )
    coin_list = portfolio_overview_data["coin_list"]
    portfolio_metrics = portfolio_overview_data["portfolio_metrics"]

    return render(
        request,
        "portfolio/overview.html",
        {
            "coin_list": coin_list,
            "total_invested": portfolio_metrics["total_invested"],
            "portfolio_value": portfolio_metrics["portfolio_value"],
            "portfolio_upl": portfolio_metrics["portfolio_upl"],
            "portfolio_upl_percentage": portfolio_metrics["portfolio_upl_percentage"],
        },
    )


@login_required
@validate_common_params_defaults
def show_all_transactions(request):
    transactions = PortfolioTransaction.get_for_user(request.user)
    page, sort, direction = get_common_params_defaults(
        request, page_count=len(transactions)
    )
    transactions = transactions.order_by(add_direction_sign(sort, direction))
    page_obj = Paginator(transactions, TRANSACTIONS_PER_PAGE).page(page)

    return render(
        request,
        "portfolio/all_transactions.html",
        {
            "page_obj": page_obj,
            "sort": sort,
            "direction": direction,
        },
    )


@login_required()
@validate_common_params_defaults
def create_portfolio_transaction(
    request, coin_id=None, cg_id=None, transaction_id=None
):
    try:
        coin = Coin.objects.filter(is_active=True)
        if coin_id:
            coin = coin.get(id=coin_id)
        else:
            coin = coin.get(cg_id=cg_id)
        transactions = PortfolioTransaction.get_for_user(request.user).filter(coin=coin)
        page, sort, direction = get_common_params_defaults(
            request, page_count=len(transactions)
        )
        transactions = transactions.order_by(add_direction_sign(sort, direction))
        page = Paginator(transactions, TRANSACTIONS_PER_PAGE).page(page)
        balance = PortfolioTransaction.get_coin_balance(request.user, coin)
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
                if coin_id:
                    return redirect("portfolio:add_transaction", coin_id=coin_id)
                else:
                    return redirect("portfolio:add_transaction_cg", cg_id=cg_id)

    return render(
        request,
        "portfolio/create_transaction.html",
        {
            "form": form,
            "coin": coin,
            "balance": balance,
            "transaction": transaction,
            "page_obj": page,
            "sort": sort,
            "direction": direction,
        },
    )


@login_required()
@require_POST
def delete_portfolio_transaction(request, coin_id, transaction_id):
    try:
        coin = Coin.objects.get(id=coin_id, is_active=True)
        transaction = PortfolioTransaction.objects.get(
            pk=transaction_id, user=request.user, coin=coin
        )

        balance = PortfolioTransaction.get_coin_balance(request.user, coin)
        if transaction.type == "buy" and balance - transaction.amount < 0:
            messages.add_message(
                request,
                messages.ERROR,
                "If you delete this sell transaction, your balance will be negative.",
            )
        else:
            transaction.delete()
        next_ = request.POST.get("next")
        if next_:
            return redirect(next_)
    except (Coin.DoesNotExist, PortfolioTransaction.DoesNotExist):
        pass
    return redirect("portfolio:add_transaction", coin_id=coin_id)
