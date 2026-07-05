"""Service-level unit tests for ``CoinGeckoClient`` (subtask 5.5).

These drive the *real* client logic (``_request`` status mapping, single JSON
decode, shape validation, cache policy, ``_sort``) against canned HTTP responses
injected through the public ``session=`` constructor seam — never patching
``_request``/``_session``/``requests`` or reaching into private methods. View
tests keep their existing delegator-patching seam; this covers the client code
those tests never reach.

The whole class runs under a LocMemCache override because ``list_supported_coins``
and cacheable market pages both hit ``django.core.cache``; the production
``DatabaseCache`` table is not created by the test runner.
"""

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from coins.exceptions import (
    CoinGeckoAuthError,
    CoinGeckoRateLimitError,
    CoinGeckoResponseError,
    CoinGeckoServerError,
    CoinGeckoUnavailableError,
)
from coins.services import CoinGeckoClient
from coins.settings import RESULTS_PAGE
from common.test_utils import (
    fake_response,
    fake_session,
    make_market_coin,
    market_response,
)


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class CoinGeckoClientTest(SimpleTestCase):
    def setUp(self):
        # LocMemCache is process-shared; isolate every test.
        cache.clear()
        self.addCleanup(cache.clear)

    # -- success ------------------------------------------------------------

    def test_get_markets_success_returns_data_and_calls_correct_endpoint(self):
        session = fake_session(
            fake_response(payload=market_response("bitcoin", "ethereum"))
        )
        client = CoinGeckoClient(session=session)

        result = client.get_markets(1, "rank", "asc")

        # rank/asc is the early-return, so order is verbatim.
        self.assertEqual([c["id"] for c in result], ["bitcoin", "ethereum"])
        session.get.assert_called_once()
        args, kwargs = session.get.call_args
        self.assertEqual(args[0], client.base_url + "coins/markets")
        self.assertEqual(
            kwargs["timeout"], (client.connect_timeout, client.read_timeout)
        )
        params = kwargs["params"]
        self.assertEqual(params["vs_currency"], "usd")
        self.assertEqual(params["order"], "market_cap_desc")
        self.assertEqual(params["page"], 1)
        self.assertEqual(params["per_page"], RESULTS_PAGE)

    def test_list_supported_coins_success_returns_data_and_calls_endpoint(self):
        payload = [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}]
        session = fake_session(fake_response(payload=payload))
        client = CoinGeckoClient(session=session)

        result = client.list_supported_coins()

        self.assertEqual(result, payload)
        session.get.assert_called_once()
        args, kwargs = session.get.call_args
        self.assertEqual(args[0], client.base_url + "coins/list")
        self.assertEqual(kwargs["params"], {"status": "active"})
        self.assertEqual(
            kwargs["timeout"], (client.connect_timeout, client.read_timeout)
        )

    # -- transport failure --------------------------------------------------

    def test_timeout_raises_unavailable(self):
        client = CoinGeckoClient(session=fake_session(error=requests.Timeout()))
        with self.assertRaises(CoinGeckoUnavailableError):
            client.get_markets(1, "rank", "asc")

    def test_connection_error_raises_unavailable(self):
        client = CoinGeckoClient(session=fake_session(error=requests.ConnectionError()))
        with self.assertRaises(CoinGeckoUnavailableError):
            client.list_supported_coins()

    # -- non-2xx status mapping --------------------------------------------

    def test_rate_limit_raises_with_retry_after(self):
        session = fake_session(
            fake_response(status=429, payload=[], headers={"Retry-After": "30"})
        )
        client = CoinGeckoClient(session=session)
        with self.assertRaises(CoinGeckoRateLimitError) as ctx:
            client.get_markets(1, "rank", "asc")
        self.assertEqual(ctx.exception.retry_after, "30")

    def test_auth_statuses_raise_auth_error(self):
        for status in (401, 403):
            with self.subTest(status=status):
                session = fake_session(fake_response(status=status, payload=[]))
                client = CoinGeckoClient(session=session)
                with self.assertRaises(CoinGeckoAuthError):
                    client.get_markets(1, "rank", "asc")

    def test_server_statuses_raise_server_error(self):
        for status in (500, 503):
            with self.subTest(status=status):
                session = fake_session(fake_response(status=status, payload=[]))
                client = CoinGeckoClient(session=session)
                with self.assertRaises(CoinGeckoServerError):
                    client.get_markets(1, "rank", "asc")

    def test_other_4xx_raises_response_error(self):
        session = fake_session(fake_response(status=404, payload=[]))
        client = CoinGeckoClient(session=session)
        with self.assertRaises(CoinGeckoResponseError):
            client.get_markets(1, "rank", "asc")

    # -- malformed / wrong-shape body --------------------------------------

    def test_malformed_json_raises_response_error(self):
        session = fake_session(fake_response(status=200, body="not json"))
        client = CoinGeckoClient(session=session)
        with self.assertRaises(CoinGeckoResponseError):
            client.get_markets(1, "rank", "asc")

    def test_supported_coins_empty_list_raises_response_error(self):
        session = fake_session(fake_response(payload=[]))
        client = CoinGeckoClient(session=session)
        with self.assertRaises(CoinGeckoResponseError):
            client.list_supported_coins()

    def test_supported_coins_non_list_raises_response_error(self):
        session = fake_session(fake_response(payload={"error": "boom"}))
        client = CoinGeckoClient(session=session)
        with self.assertRaises(CoinGeckoResponseError):
            client.list_supported_coins()

    def test_markets_non_list_raises_response_error(self):
        session = fake_session(fake_response(payload={"error": "boom"}))
        client = CoinGeckoClient(session=session)
        with self.assertRaises(CoinGeckoResponseError):
            client.get_markets(1, "rank", "asc")

    # -- empty ids short-circuit -------------------------------------------

    def test_empty_ids_returns_empty_without_network_call(self):
        session = fake_session(fake_response(payload=[]))
        client = CoinGeckoClient(session=session)

        result = client.get_markets(1, "rank", "asc", ids=[])

        self.assertEqual(result, [])
        session.get.assert_not_called()

    # -- cache policy -------------------------------------------------------

    def test_market_page_is_cached_single_fetch(self):
        session = fake_session(fake_response(payload=market_response("bitcoin")))
        client = CoinGeckoClient(session=session)

        client.get_markets(1, "rank", "asc")
        client.get_markets(1, "rank", "asc")

        self.assertEqual(session.get.call_count, 1)

    def test_supported_coins_is_cached_single_fetch(self):
        payload = [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}]
        session = fake_session(fake_response(payload=payload))
        client = CoinGeckoClient(session=session)

        client.list_supported_coins()
        client.list_supported_coins()

        self.assertEqual(session.get.call_count, 1)

    def test_id_specific_markets_are_not_cached_refetches(self):
        session = fake_session(fake_response(payload=market_response("bitcoin")))
        client = CoinGeckoClient(session=session)

        client.get_markets(1, "rank", "asc", ids=["bitcoin"])
        client.get_markets(1, "rank", "asc", ids=["bitcoin"])

        self.assertEqual(session.get.call_count, 2)

    # -- sort tolerates missing keys ---------------------------------------

    def test_sort_tolerates_coin_missing_the_sort_key(self):
        has_price = make_market_coin("haspricecoin", current_price=100.0)
        no_price = make_market_coin("nopricecoin")
        del no_price["current_price"]
        session = fake_session(fake_response(payload=[no_price, has_price]))
        client = CoinGeckoClient(session=session)

        # Sort by price desc via the public method; the missing key sorts as 0.
        result = client.get_markets(
            1, "price", "desc", ids=["haspricecoin", "nopricecoin"]
        )

        self.assertEqual([c["id"] for c in result], ["haspricecoin", "nopricecoin"])
