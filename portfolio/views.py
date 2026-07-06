import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from coins.exceptions import CoinGeckoError
from coins.models import Coin
from common.decorators.views import validate_common_params
from common.utils import (
    add_direction_sign,
    get_common_params,
    get_safe_redirect_url,
    handle_market_unavailable,
)
from portfolio.exceptions import LedgerError
from portfolio.forms import PortfolioTransactionForm
from portfolio.ledger import (
    create_transaction,
    delete_transaction,
    update_transaction,
)
from portfolio.models import PortfolioTransaction
from portfolio.services import get_portfolio_overview_data
from portfolio.settings import (
    ALLOWED_SORTS,
    DEFAULT_DIRECTION,
    DEFAULT_SORT,
    OVERVIEW_ALLOWED_SORTS,
    TRANSACTIONS_PER_PAGE,
)

logger = logging.getLogger(__name__)

validate_common_params_defaults = validate_common_params(ALLOWED_SORTS)
get_common_params_defaults = get_common_params(DEFAULT_SORT, DEFAULT_DIRECTION)


@login_required
@validate_common_params(OVERVIEW_ALLOWED_SORTS)
def portfolio_overview(request):
    positive_balance_coin_ids = PortfolioTransaction.get_positive_coin_balance_ids(
        user=request.user
    )
    cg_to_db_id_map = {
        item["coin__cg_id"]: item["coin_id"] for item in positive_balance_coin_ids
    }

    sort = request.GET.get("sort", "allocation_percentage")
    direction = request.GET.get("direction", "desc")
    context = {
        "sort": sort,
        "direction": direction,
        "coin_list": [],
    }

    try:
        portfolio_overview_data = get_portfolio_overview_data(
            user=request.user, cg_to_db_id_map=cg_to_db_id_map
        )
        coin_list = portfolio_overview_data["coin_list"]
        portfolio_metrics = portfolio_overview_data["portfolio_metrics"]
        # None-safe sort: unpriced holdings carry None in the market-derived
        # columns, which cannot be compared against Decimal. Partition first so
        # None never reaches the comparison, then always append unpriced rows to
        # the end regardless of sort direction.
        priced_rows = [c for c in coin_list if c[sort] is not None]
        unpriced_rows = [c for c in coin_list if c[sort] is None]
        priced_rows.sort(key=lambda x: x[sort], reverse=(direction == "desc"))
        coin_list = priced_rows + unpriced_rows
        context.update(
            {
                "coin_list": coin_list,
                "total_invested": portfolio_metrics["total_invested"],
                "portfolio_value": portfolio_metrics["portfolio_value"],
                "portfolio_upl": portfolio_metrics["portfolio_upl"],
                "portfolio_upl_percentage": portfolio_metrics[
                    "portfolio_upl_percentage"
                ],
                "unpriced_count": portfolio_metrics["unpriced_count"],
            }
        )
    except CoinGeckoError as exc:
        # Whole market call failed: show the banner in place of both the summary
        # tiles and the P/L table. Rendering holdings without live prices is
        # step 11.4 territory, not this subtask.
        context.update(handle_market_unavailable(logger, exc))

    return render(request, "portfolio/overview.html", context)


@login_required
@validate_common_params_defaults
def show_all_transactions(request):
    transactions = PortfolioTransaction.get_for_user(request.user)
    page, sort, direction = get_common_params_defaults(request, page_count=None)
    transactions = transactions.order_by(add_direction_sign(sort, direction))
    paginator = Paginator(transactions, TRANSACTIONS_PER_PAGE)
    page, sort, direction = get_common_params_defaults(
        request, page_count=paginator.num_pages
    )
    page_obj = paginator.page(page)

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
        # Delisted (is_active=False) coins still resolve here: the per-coin page
        # renders history + balance read-only, and mutation permission is
        # enforced in the ledger (buys blocked, sells/deletes allowed) — 11.6.
        coin = Coin.objects.all()
        if coin_id:
            coin = coin.get(id=coin_id)
        else:
            coin = coin.get(cg_id=cg_id)
        transactions = PortfolioTransaction.get_for_user(request.user).filter(coin=coin)
        page, sort, direction = get_common_params_defaults(request, page_count=None)
        transactions = transactions.order_by(add_direction_sign(sort, direction))
        paginator = Paginator(transactions, TRANSACTIONS_PER_PAGE)
        page, sort, direction = get_common_params_defaults(
            request, page_count=paginator.num_pages
        )
        page = paginator.page(page)
        balance = PortfolioTransaction.get_coin_balance(request.user, coin)
        transaction = None
        if transaction_id:
            transaction = transactions.get(id=transaction_id)
    except (Coin.DoesNotExist, PortfolioTransaction.DoesNotExist):
        return redirect("coins:watchlist")

    form = PortfolioTransactionForm(request.POST or None, instance=transaction)
    if request.method == "POST":
        if form.is_valid():
            try:
                if transaction is not None:
                    update_transaction(
                        transaction=transaction,
                        type=form.cleaned_data["type"],
                        amount=form.cleaned_data["amount"],
                        price=form.cleaned_data["price"],
                        trade_date=form.cleaned_data["trade_date"],
                    )
                else:
                    create_transaction(
                        user=request.user,
                        coin=coin,
                        type=form.cleaned_data["type"],
                        amount=form.cleaned_data["amount"],
                        price=form.cleaned_data["price"],
                        trade_date=form.cleaned_data["trade_date"],
                    )
            except LedgerError as exc:
                form.add_error("amount", str(exc))
            else:
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
        coin = Coin.objects.get(id=coin_id)
        transaction = PortfolioTransaction.objects.get(
            pk=transaction_id, user=request.user, coin=coin
        )

        try:
            delete_transaction(transaction=transaction)
        except LedgerError as exc:
            messages.add_message(request, messages.ERROR, str(exc))
        next_url = get_safe_redirect_url(request, request.POST.get("next"))
        if next_url:
            return redirect(next_url)
    except (Coin.DoesNotExist, PortfolioTransaction.DoesNotExist):
        pass
    return redirect("portfolio:add_transaction", coin_id=coin_id)
