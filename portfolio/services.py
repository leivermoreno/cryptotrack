from collections import defaultdict, deque
from decimal import Decimal

from coins.services import get_coin_list_with_market
from portfolio.models import PortfolioTransaction


def get_portfolio_overview_data(user, cg_to_db_id_map):
    holdings = build_holdings(user=user, coin_ids=cg_to_db_id_map.values())
    market_data = get_coin_list_with_market(
        1, "rank", "asc", ids=cg_to_db_id_map.keys()
    )
    coin_list = []
    for coin in market_data:
        positions = holdings[coin["id"]]
        amount = sum([p["amount"] for p in positions])
        total_invested = sum([p["amount"] * p["price"] for p in positions])
        avg_buy_price = total_invested / amount if amount > 0 else 0
        current_price = Decimal(coin["current_price"])
        upl = amount * current_price - total_invested
        upl_percentage = (upl / total_invested * 100) if total_invested > 0 else 0

        coin_list.append(
            {
                "coin_id": cg_to_db_id_map[coin["id"]],
                "coin_name": coin["name"],
                "coin_symbol": coin["symbol"],
                "current_price": current_price,
                "avg_buy_price": avg_buy_price,
                "amount": amount,
                "total_invested": total_invested,
                "upl": upl,
                "upl_percentage": upl_percentage,
            }
        )

    portfolio_metrics = calculate_portfolio_metrics(coin_list)

    for coin in coin_list:
        coin["allocation_percentage"] = (
            coin["amount"]
            * coin["current_price"]
            / portfolio_metrics["portfolio_value"]
            * 100
        )

    return {"coin_list": coin_list, "portfolio_metrics": portfolio_metrics}


def build_holdings(user, coin_ids):
    # query only transactions for provided coin_ids
    transactions = (
        PortfolioTransaction.objects.filter(
            user=user, coin_id__in=coin_ids, coin__is_active=True
        )
        .order_by("created")
        .select_related("coin")
    )
    holdings = defaultdict(deque)
    for tx in transactions:
        # if a buy transaction, add a lot to the holdings
        if tx.type == "buy":
            holdings[tx.coin.cg_id].append({"amount": tx.amount, "price": tx.price})
        # if a sell transaction, remove from the oldest lot(s) in the holdings (FIFO)
        else:
            amount_to_sell = tx.amount
            # sell while there's still amount left
            while amount_to_sell > 0:
                position = holdings[tx.coin.cg_id][0]
                # if lot is smaller than or equal to amount to sell, remove the lot from the beginning of the deque
                if position["amount"] <= amount_to_sell:
                    amount_to_sell -= position["amount"]
                    holdings[tx.coin.cg_id].popleft()
                # if lot is larger than amount to sell, reduce the lot size
                else:
                    position["amount"] -= amount_to_sell
                    amount_to_sell = 0

    return holdings


def calculate_portfolio_metrics(coin_list):
    total_invested = sum([c["total_invested"] for c in coin_list])
    portfolio_value = sum([c["amount"] * c["current_price"] for c in coin_list])
    portfolio_upl = sum([c["upl"] for c in coin_list])
    portfolio_upl_percentage = (
        portfolio_upl / total_invested * 100 if total_invested > 0 else 0
    )

    return {
        "total_invested": total_invested,
        "portfolio_value": portfolio_value,
        "portfolio_upl": portfolio_upl,
        "portfolio_upl_percentage": portfolio_upl_percentage,
    }
