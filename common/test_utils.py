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

Service-level test doubles
--------------------------
``fake_response``/``fake_session`` drive the *real* ``CoinGeckoClient`` logic
against canned HTTP without patching ``_request``/``_session`` or ``requests``.
Inject the fake session via the constructor: ``CoinGeckoClient(session=...)``.
``fake_response`` returns a real ``requests.models.Response`` so ``.json()`` and
``.raise_for_status()`` behave faithfully (a bad body raises ``ValueError``; a
4xx/5xx status raises ``HTTPError``).
"""

import json

import requests


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

    ``cg_id`` populates both the raw CoinGecko ``id`` key (e.g. ``"bitcoin"``)
    and the normalized ``cg_id`` key that ``CoinGeckoClient.get_markets`` adds
    at read time — so payloads returned by a *patched* client (view tests)
    carry ``cg_id`` for the templates, and payloads fed as raw HTTP bodies to
    the *real* client (service tests) are re-normalized harmlessly.
    """
    coin = {
        "id": cg_id,
        "cg_id": cg_id,
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


def fake_response(status=200, payload=None, body=None, headers=None):
    """Build a real ``requests.Response`` for injecting into a fake session.

    - ``payload``: JSON-serializable value for the body (``.json()`` returns it).
    - ``body``: raw string body used verbatim (for malformed-JSON cases); takes
      precedence over ``payload``.
    - ``status``/``headers``: HTTP status code and response headers.
    """
    response = requests.models.Response()
    response.status_code = status
    if headers:
        response.headers.update(headers)
    if body is not None:
        content = body
    elif payload is not None:
        content = json.dumps(payload)
    else:
        content = ""
    response._content = content.encode("utf-8")
    return response


def fake_session(response=None, error=None):
    """Return a stand-in session whose ``.get`` returns ``response`` or raises.

    Pass ``error`` (e.g. ``requests.Timeout()``) to simulate a transport failure;
    otherwise ``.get`` returns ``response``. The returned object records calls, so
    tests can assert call count and the URL/params/timeout passed.
    """
    from unittest import mock

    session = mock.Mock()
    if error is not None:
        session.get.side_effect = error
    else:
        session.get.return_value = response
    return session
