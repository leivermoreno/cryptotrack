"""Shared test helpers for mocking CoinGecko market data offline.

All CoinGecko HTTP lives in ``coins/services.py``. View tests must never make
live network calls; instead patch the names *where they are looked up* (not
``coins.services.*``) and return payloads built with the factories here.

Patch targets
-------------
- ``coins/views.py`` imports both functions at module top, so patch:
    - ``coins.views.get_coin_list_with_market``
    - ``coins.views.get_page_count``
- ``portfolio/services.py`` imports the market call at module top, so patch:
    - ``portfolio.services.get_coin_list_with_market``
  The portfolio overview *view* reaches CoinGecko only via
  ``get_portfolio_overview_data`` -> ``portfolio.services.get_coin_list_with_market``,
  so patching that one name covers the overview view tests.

Payload shape
-------------
``get_coin_list_with_market`` returns a list of dicts, one per coin. The keys
consumed by templates and portfolio math are produced by ``make_market_coin``.
The numeric fields (``current_price``/``ath``/``total_volume``/``market_cap``)
are Python ``float``s, matching CoinGecko's JSON numbers: the ``coins``
templates format them via ``format_number`` (which calls ``int(value)`` and so
rejects strings), and ``Decimal(float)`` in ``portfolio/services.py`` is valid.

Note: ``get_page_count`` returns an int (return a small value such as ``1``).
"""


def make_market_coin(
    cg_id="bitcoin",
    name="Bitcoin",
    symbol="btc",
    current_price=30000.0,
    market_cap_rank=1,
    price_change_percentage_24h_in_currency=1.5,
    price_change_percentage_7d_in_currency=5.0,
    ath=69000.0,
    total_volume=1000000.0,
    market_cap=600000000.0,
    **overrides,
):
    """Return one market-data dict with all template/math keys (overrides win).

    ``cg_id`` maps to the CoinGecko ``id`` key (e.g. ``"bitcoin"``).
    """
    coin = {
        "id": cg_id,
        "name": name,
        "symbol": symbol,
        "current_price": current_price,
        "market_cap_rank": market_cap_rank,
        "price_change_percentage_24h_in_currency": (
            price_change_percentage_24h_in_currency
        ),
        "price_change_percentage_7d_in_currency": (
            price_change_percentage_7d_in_currency
        ),
        "ath": ath,
        "total_volume": total_volume,
        "market_cap": market_cap,
    }
    coin.update(overrides)
    return coin


def market_response(*coins):
    """Build a list of market-data dicts.

    Each argument may be a ``cg_id`` string (passed to ``make_market_coin``) or
    an already-built dict (used as-is).
    """
    result = []
    for coin in coins:
        if isinstance(coin, dict):
            result.append(coin)
        else:
            result.append(make_market_coin(cg_id=coin, name=coin.capitalize()))
    return result
