from collections import defaultdict, deque
from decimal import Decimal

from coins.models import Coin
from coins.services import get_coin_list_with_market
from portfolio.models import PortfolioTransaction


def get_portfolio_overview_data(user, cg_to_db_id_map):
    holdings = build_holdings(user=user, coin_ids=cg_to_db_id_map.values())
    market_data = get_coin_list_with_market(
        1, "rank", "asc", ids=cg_to_db_id_map.keys()
    )
    market_by_id = {coin["id"]: coin for coin in market_data}
    # Coin table is the authoritative source for name/symbol/is_active. It backs
    # name/symbol for holdings absent from the market payload (partial response,
    # id not returned) and, for delisted holdings (is_active=False, kept visible
    # read-only per 11.6), supplies both the fallback name/symbol and the flag
    # that drives the "Delisted" badge. is_active is attached to every row below
    # regardless of whether it was priced, so the badge is independent of price.
    coin_meta = {
        coin["cg_id"]: coin
        for coin in Coin.objects.filter(id__in=cg_to_db_id_map.values()).values(
            "id", "cg_id", "name", "symbol", "is_active"
        )
    }

    coin_list = []
    # Iterate over every positive-balance holding, not just the ones the market
    # returned, so a holding with missing/unknown price is shown instead of
    # silently dropped.
    for cg_id, db_id in cg_to_db_id_map.items():
        positions = holdings[cg_id]
        amount = sum([p["amount"] for p in positions])
        total_invested = sum([p["amount"] * p["price"] for p in positions])
        avg_buy_price = total_invested / amount if amount > 0 else 0

        market_coin = market_by_id.get(cg_id)
        has_price = (
            market_coin is not None and market_coin.get("current_price") is not None
        )

        if has_price:
            current_price = Decimal(str(market_coin["current_price"]))
            upl = amount * current_price - total_invested
            upl_percentage = (upl / total_invested * 100) if total_invested > 0 else 0
            coin_list.append(
                {
                    "id": db_id,
                    "name": market_coin["name"],
                    "symbol": market_coin["symbol"],
                    "is_active": coin_meta.get(cg_id, {}).get("is_active", True),
                    "price": current_price,
                    "avg_buy_price": avg_buy_price,
                    "amount": amount,
                    "cost_basis": total_invested,
                    "market_value": amount * current_price,
                    "upl": upl,
                    "upl_percentage": upl_percentage,
                }
            )
        else:
            # Unpriced holding: keep the ledger facts (amount/cost_basis/avg buy
            # price) and render the market-derived fields as None ("-" via the
            # format filters). Name/symbol come from the Coin table.
            meta = coin_meta.get(cg_id, {})
            coin_list.append(
                {
                    "id": db_id,
                    "name": meta.get("name", cg_id),
                    "symbol": meta.get("symbol", ""),
                    "is_active": meta.get("is_active", True),
                    "price": None,
                    "avg_buy_price": avg_buy_price,
                    "amount": amount,
                    "cost_basis": total_invested,
                    "market_value": None,
                    "upl": None,
                    "upl_percentage": None,
                }
            )

    portfolio_metrics = calculate_portfolio_metrics(coin_list)

    for coin in coin_list:
        # Unpriced holdings have no market value and are excluded from the
        # allocation denominator, so they get no allocation percentage.
        if coin["market_value"] is None:
            coin["allocation_percentage"] = None
        elif portfolio_metrics["portfolio_value"] == 0:
            # Every priced holding is worth 0 (e.g. all current prices are 0), so
            # allocation is 0/0 — undefined. Report 0% to stay on the priced path
            # and match the mixed case, where a 0-value holding is 0% of a nonzero
            # portfolio.
            coin["allocation_percentage"] = Decimal("0")
        else:
            coin["allocation_percentage"] = (
                coin["market_value"] / portfolio_metrics["portfolio_value"] * 100
            )

    return {"coin_list": coin_list, "portfolio_metrics": portfolio_metrics}


def build_holdings(user, coin_ids):
    # query only transactions for provided coin_ids
    transactions = (
        PortfolioTransaction.objects.filter(user=user, coin_id__in=coin_ids)
        .order_by("trade_date", "id")
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
            lots = holdings[tx.coin.cg_id]
            # Sell while there's amount left AND lots remain. The lot guard makes
            # build_holdings tolerate oversold history (a sell exceeding available
            # buy lots): consume what exists, drop the un-backed excess, and never
            # index an empty deque. Oversells can't be created through the app
            # (portfolio.ledger enforces feasibility) but can arrive via raw DB /
            # admin edits or imported history.
            while amount_to_sell > 0 and lots:
                position = lots[0]
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
    # Sum only over priced holdings so every total covers the same set and stays
    # internally consistent (invested/value/UPL). Unpriced holdings are excluded
    # and surfaced separately via unpriced_count.
    priced = [c for c in coin_list if c["market_value"] is not None]
    total_invested = sum([c["cost_basis"] for c in priced])
    portfolio_value = sum([c["market_value"] for c in priced])
    portfolio_upl = sum([c["upl"] for c in priced])
    portfolio_upl_percentage = (
        portfolio_upl / total_invested * 100 if total_invested > 0 else 0
    )

    return {
        "total_invested": total_invested,
        "portfolio_value": portfolio_value,
        "portfolio_upl": portfolio_upl,
        "portfolio_upl_percentage": portfolio_upl_percentage,
        "unpriced_count": len(coin_list) - len(priced),
    }
