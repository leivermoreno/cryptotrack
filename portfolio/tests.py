from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from coins.exceptions import CoinGeckoUnavailableError
from coins.models import Coin
from common.test_utils import make_market_coin, market_response
from portfolio.exceptions import LedgerError
from portfolio.forms import PortfolioTransactionForm
from portfolio.ledger import create_transaction, update_transaction
from portfolio.services import build_holdings, get_portfolio_overview_data

from .models import PortfolioTransaction

User = get_user_model()


def _make_tx(user, coin, type, amount, price, created=None, trade_date=None):
    """Create a transaction, optionally forcing the auto_now_add ``created``."""
    create_kwargs = {
        "user": user,
        "coin": coin,
        "type": type,
        "amount": amount,
        "price": price,
    }
    if trade_date is not None:
        create_kwargs["trade_date"] = trade_date
    tx = PortfolioTransaction.objects.create(**create_kwargs)
    if created is not None:
        PortfolioTransaction.objects.filter(pk=tx.pk).update(created=created)
        tx.refresh_from_db()
    return tx


class PortfolioTransactionModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")

    def test_get_for_user_returns_transactions(self):
        tx = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        txs = PortfolioTransaction.get_for_user(self.user)
        self.assertEqual(txs.count(), 1)
        self.assertIn(tx, txs)

    def test_get_coin_balance_buy_and_sell(self):
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="sell", amount=1, price=12000
        )
        balance = PortfolioTransaction.get_coin_balance(self.user, self.coin)
        self.assertEqual(balance, 1)

    def test_get_positive_coin_balance_ids(self):
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        ids = PortfolioTransaction.get_positive_coin_balance_ids(self.user)
        coin_ids = [item["coin_id"] for item in ids]
        self.assertIn(self.coin.id, coin_ids)

    def test_zero_or_negative_balance_not_in_positive_ids(self):
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=1, price=10000
        )
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="sell", amount=1, price=12000
        )
        ids = PortfolioTransaction.get_positive_coin_balance_ids(self.user)
        coin_ids = [item["coin_id"] for item in ids]
        self.assertNotIn(self.coin.id, coin_ids)

    def test_meta_indexes_are_the_two_expected_composites(self):
        # Pin the index set. The (user, coin, trade_date, id) composite serves
        # the ledger lock path / build_holdings / balance; (user, trade_date)
        # serves the default list sort. Guards against accidental additions/removals.
        indexes = {
            index.name: index.fields for index in PortfolioTransaction._meta.indexes
        }
        self.assertEqual(
            indexes,
            {
                "pf_txn_user_coin_trade_date_id": [
                    "user",
                    "coin",
                    "trade_date",
                    "id",
                ],
                "pf_txn_user_trade_date": ["user", "trade_date"],
            },
        )


class PortfolioTransactionAdminSmokeTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pass"
        )
        self.user = User.objects.create_user(username="trader", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.transaction = PortfolioTransaction.objects.create(
            user=self.user,
            coin=self.coin,
            type="buy",
            amount=Decimal("2.5"),
            price=Decimal("10000"),
        )
        self.client.force_login(self.admin_user)

    def test_admin_list_and_view_pages_load(self):
        response = self.client.get(
            reverse("admin:portfolio_portfoliotransaction_changelist")
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "trader")
        self.assertContains(response, "Bitcoin")

        response = self.client.get(
            reverse(
                "admin:portfolio_portfoliotransaction_change",
                args=[self.transaction.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bitcoin")
        self.assertContains(response, "Trade date")
        self.assertNotContains(response, 'name="_save"')

    def test_admin_add_page_is_disabled(self):
        response = self.client.get(reverse("admin:portfolio_portfoliotransaction_add"))
        self.assertEqual(response.status_code, 403)


class PortfolioViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )

    @patch(
        "portfolio.services.get_coin_list_with_market",
        return_value=market_response("bitcoin"),
    )
    def test_portfolio_overview_authenticated(self, mock_market):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(reverse("portfolio:overview"))
        self.assertTrue(mock_market.called)
        coin_list = response.context["coin_list"]
        coin_names = [c["name"] for c in coin_list]
        self.assertIn(self.coin.name, coin_names)
        # Check portfolio metrics keys
        for key in [
            "total_invested",
            "portfolio_value",
            "portfolio_upl",
            "portfolio_upl_percentage",
        ]:
            self.assertIn(key, response.context)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "portfolio/overview.html")
        self.assertIn("coin_list", response.context)

    def test_portfolio_overview_unauthenticated(self):
        url = reverse("portfolio:overview")
        response = self.client.get(url)
        self.assertRedirects(response, reverse("accounts:login", query={"next": url}))

    @patch("portfolio.services.get_coin_list_with_market", return_value=[])
    def test_portfolio_overview_no_transactions(self, mock_market):
        User.objects.create_user(username="testuser2", password="pass")
        self.client.login(username="testuser2", password="pass")
        response = self.client.get(reverse("portfolio:overview"))
        self.assertContains(response, "No open holdings in your portfolio.")
        self.assertContains(response, "Browse coins")
        self.assertEqual(len(response.context["coin_list"]), 0)

    @patch(
        "portfolio.services.get_coin_list_with_market",
        return_value=market_response("bitcoin", "ethereum"),
    )
    def test_portfolio_overview_sorting(self, mock_market):
        self.client.login(username="testuser", password="pass")
        # Add another coin with a different allocation
        coin2 = Coin.objects.create(cg_id="ethereum", name="Ethereum", symbol="ETH")
        PortfolioTransaction.objects.create(
            user=self.user, coin=coin2, type="buy", amount=1, price=20000
        )
        response = self.client.get(
            reverse("portfolio:overview") + "?sort=allocation_percentage&direction=asc"
        )
        self.assertEqual(response.status_code, 200)
        coin_list = response.context["coin_list"]
        # should be sorted in ascending order by allocation_percentage
        allocs = [c["allocation_percentage"] for c in coin_list]
        self.assertEqual(allocs, sorted(allocs))

    @patch(
        "portfolio.services.get_coin_list_with_market",
        side_effect=CoinGeckoUnavailableError("down"),
    )
    def test_portfolio_overview_market_failure_renders_banner(self, mock_market):
        # 5.6: whole market call fails -> banner in place of summary tiles AND
        # the P/L table, HTTP 200, no 500. Holdings-without-prices is step 11.4.
        self.client.login(username="testuser", password="pass")
        response = self.client.get(reverse("portfolio:overview"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "portfolio/overview.html")
        self.assertTrue(response.context["market_unavailable"])
        self.assertEqual(response.context["coin_list"], [])
        self.assertContains(
            response,
            "Market data is temporarily unavailable",
        )
        self.assertNotContains(response, "No open holdings in your portfolio.")
        # No P/L summary metric keys were populated.
        self.assertNotIn("portfolio_value", response.context)

    @patch(
        "portfolio.services.get_coin_list_with_market",
        return_value=market_response("bitcoin"),
    )
    def test_partial_payload_shows_unpriced_row_and_sorts_safely(self, mock_market):
        # 11.4: a partial payload (some ids missing) is not an error. The
        # missing holding is rendered as an unpriced row, the view returns 200,
        # and sorting by a market-derived column (or the default) does not raise
        # on the None values.
        self.client.login(username="testuser", password="pass")
        eth = Coin.objects.create(cg_id="ethereum", name="Ethereum", symbol="ETH")
        PortfolioTransaction.objects.create(
            user=self.user, coin=eth, type="buy", amount=1, price=20000
        )
        # Default sort (allocation_percentage, desc) must not raise on None.
        response = self.client.get(reverse("portfolio:overview"))
        self.assertEqual(response.status_code, 200)
        symbols = [c["symbol"] for c in response.context["coin_list"]]
        self.assertIn("ETH", symbols)  # unpriced holding still shown
        self.assertEqual(response.context["unpriced_count"], 1)
        self.assertContains(response, "excluded from totals")
        # Explicit sort by a market-derived column must also be None-safe.
        response = self.client.get(
            reverse("portfolio:overview") + "?sort=price&direction=asc"
        )
        self.assertEqual(response.status_code, 200)
        rows = response.context["coin_list"]
        # Unpriced rows sink to the end regardless of direction.
        self.assertIsNone(rows[-1]["price"])


# ---------------------------------------------------------------------------
# 2.5 — FIFO lot building (build_holdings)
# ---------------------------------------------------------------------------
class BuildHoldingsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="fifo", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.coin2 = Coin.objects.create(
            cg_id="ethereum", name="Ethereum", symbol="ETH"
        )
        self.base = timezone.now()

    def _holdings(self):
        return build_holdings(self.user, [self.coin.id, self.coin2.id])

    def test_single_buy_makes_one_lot(self):
        _make_tx(self.user, self.coin, "buy", 2, 10000, created=self.base)
        lots = list(self._holdings()[self.coin.cg_id])
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0]["amount"], Decimal("2"))
        self.assertEqual(lots[0]["price"], Decimal("10000"))

    def test_two_buys_preserve_order(self):
        _make_tx(self.user, self.coin, "buy", 2, 10000, created=self.base)
        _make_tx(
            self.user,
            self.coin,
            "buy",
            3,
            20000,
            created=self.base + timedelta(hours=1),
        )
        lots = list(self._holdings()[self.coin.cg_id])
        self.assertEqual([lot["amount"] for lot in lots], [Decimal("2"), Decimal("3")])

    def test_partial_sell_reduces_oldest_lot(self):
        _make_tx(self.user, self.coin, "buy", 2, 10000, created=self.base)
        _make_tx(
            self.user,
            self.coin,
            "sell",
            1,
            12000,
            created=self.base + timedelta(hours=1),
        )
        lots = list(self._holdings()[self.coin.cg_id])
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0]["amount"], Decimal("1"))

    def test_sell_spanning_lots_consumes_fifo(self):
        _make_tx(self.user, self.coin, "buy", 2, 10000, created=self.base)
        _make_tx(
            self.user,
            self.coin,
            "buy",
            3,
            20000,
            created=self.base + timedelta(hours=1),
        )
        _make_tx(
            self.user,
            self.coin,
            "sell",
            4,
            25000,
            created=self.base + timedelta(hours=2),
        )
        lots = list(self._holdings()[self.coin.cg_id])
        # first lot (2) fully consumed, second lot (3) reduced to 1
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0]["amount"], Decimal("1"))
        self.assertEqual(lots[0]["price"], Decimal("20000"))

    def test_exact_full_sell_empties_deque(self):
        _make_tx(self.user, self.coin, "buy", 2, 10000, created=self.base)
        _make_tx(
            self.user,
            self.coin,
            "sell",
            2,
            12000,
            created=self.base + timedelta(hours=1),
        )
        self.assertEqual(len(self._holdings()[self.coin.cg_id]), 0)

    def test_multiple_coins_are_isolated(self):
        _make_tx(self.user, self.coin, "buy", 2, 10000, created=self.base)
        _make_tx(self.user, self.coin2, "buy", 5, 3000, created=self.base)
        holdings = self._holdings()
        self.assertEqual(holdings[self.coin.cg_id][0]["amount"], Decimal("2"))
        self.assertEqual(holdings[self.coin2.cg_id][0]["amount"], Decimal("5"))

    def test_same_timestamp_fifo_uses_id_tiebreak(self):
        # Two buys share the exact same trade date; FIFO must consume the
        # earlier-inserted (lower-id) lot first. Without the ``id`` tiebreak
        # in build_holdings' ordering this would be nondeterministic.
        _make_tx(self.user, self.coin, "buy", 1, 10000, created=self.base)
        _make_tx(self.user, self.coin, "buy", 1, 20000, created=self.base)
        _make_tx(
            self.user,
            self.coin,
            "sell",
            1,
            25000,
            created=self.base + timedelta(hours=1),
        )
        lots = list(self._holdings()[self.coin.cg_id])
        # first buy (price 10000, lower id) consumed; second buy (20000) remains
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0]["price"], Decimal("20000"))

    def test_fifo_uses_trade_date_before_insertion_order(self):
        base_date = timezone.localdate() - timedelta(days=10)
        _make_tx(
            self.user,
            self.coin,
            "buy",
            1,
            10000,
            trade_date=base_date + timedelta(days=1),
        )
        _make_tx(
            self.user,
            self.coin,
            "buy",
            1,
            20000,
            trade_date=base_date,
        )
        _make_tx(
            self.user,
            self.coin,
            "sell",
            1,
            25000,
            trade_date=base_date + timedelta(days=2),
        )

        lots = list(self._holdings()[self.coin.cg_id])

        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0]["price"], Decimal("10000"))

    def test_oversold_history_does_not_crash(self):
        # Step 11.1: an oversold history (sell exceeding available buy lots) can
        # exist via raw DB / admin edits or imported history even though the app
        # blocks it on create. build_holdings clamps: it consumes what lots exist,
        # drops the un-backed excess, and returns a dict instead of raising
        # IndexError on the empty deque. The oversold coin ends with no open lots.
        _make_tx(self.user, self.coin, "buy", 1, 10000, created=self.base)
        _make_tx(
            self.user,
            self.coin,
            "sell",
            2,
            12000,
            created=self.base + timedelta(hours=1),
        )
        holdings = build_holdings(self.user, [self.coin.id])
        self.assertIsInstance(holdings, dict)
        self.assertEqual(list(holdings[self.coin.cg_id]), [])


# ---------------------------------------------------------------------------
# 2.5 — overview data assembly with market data mocked
# ---------------------------------------------------------------------------
class OverviewDataTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ov", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        self.map = {self.coin.cg_id: self.coin.id}

    def test_overview_math_with_mocked_price(self):
        # buy 2 @ 10000, current price 15000
        market = [make_market_coin("bitcoin", current_price=15000.0)]
        with patch("portfolio.services.get_coin_list_with_market", return_value=market):
            data = get_portfolio_overview_data(self.user, self.map)
        coin = data["coin_list"][0]
        self.assertEqual(coin["amount"], Decimal("2"))
        self.assertEqual(coin["cost_basis"], Decimal("20000"))
        self.assertEqual(coin["avg_buy_price"], Decimal("10000"))
        self.assertEqual(coin["price"], Decimal("15000"))
        self.assertEqual(coin["market_value"], Decimal("30000"))
        self.assertEqual(coin["upl"], Decimal("10000"))
        self.assertEqual(coin["upl_percentage"], Decimal("50"))
        self.assertEqual(coin["allocation_percentage"], Decimal("100"))
        metrics = data["portfolio_metrics"]
        self.assertEqual(metrics["total_invested"], Decimal("20000"))
        self.assertEqual(metrics["portfolio_value"], Decimal("30000"))
        self.assertEqual(metrics["portfolio_upl"], Decimal("10000"))

    def test_holding_missing_from_market_is_shown_unpriced(self):
        # 11.4: a positive-balance coin absent from the market response is no
        # longer silently dropped. It is shown with its ledger facts (amount,
        # cost_basis, avg_buy_price) intact and the market-derived fields as
        # None; name/symbol come from the Coin table.
        with patch("portfolio.services.get_coin_list_with_market", return_value=[]):
            data = get_portfolio_overview_data(self.user, self.map)
        self.assertEqual(len(data["coin_list"]), 1)
        coin = data["coin_list"][0]
        # Name/symbol sourced from the Coin table (not the market payload).
        self.assertEqual(coin["name"], "Bitcoin")
        self.assertEqual(coin["symbol"], "BTC")
        # Ledger-derived facts survive.
        self.assertEqual(coin["amount"], Decimal("2"))
        self.assertEqual(coin["cost_basis"], Decimal("20000"))
        self.assertEqual(coin["avg_buy_price"], Decimal("10000"))
        # Market-derived fields are unavailable.
        self.assertIsNone(coin["price"])
        self.assertIsNone(coin["market_value"])
        self.assertIsNone(coin["upl"])
        self.assertIsNone(coin["upl_percentage"])
        self.assertIsNone(coin["allocation_percentage"])
        # The unpriced holding is excluded from all totals (Option C) and
        # surfaced via unpriced_count.
        metrics = data["portfolio_metrics"]
        self.assertEqual(metrics["total_invested"], 0)
        self.assertEqual(metrics["portfolio_value"], 0)
        self.assertEqual(metrics["portfolio_upl"], 0)
        self.assertEqual(metrics["unpriced_count"], 1)

    def test_mixed_priced_and_unpriced_totals_cover_priced_only(self):
        # 11.4 Option C: totals sum only over priced holdings so they stay
        # internally consistent; the unpriced holding is excluded and counted.
        eth = Coin.objects.create(cg_id="ethereum", name="Ethereum", symbol="ETH")
        PortfolioTransaction.objects.create(
            user=self.user, coin=eth, type="buy", amount=3, price=1000
        )
        id_map = {
            self.coin.cg_id: self.coin.id,
            eth.cg_id: eth.id,
        }
        # Only bitcoin is priced (buy 2 @ 10000, price 15000); ethereum missing.
        market = [make_market_coin("bitcoin", current_price=15000.0)]
        with patch("portfolio.services.get_coin_list_with_market", return_value=market):
            data = get_portfolio_overview_data(self.user, id_map)

        # Key by name: priced rows keep the market payload's fields, unpriced
        # rows source name/symbol from the Coin table.
        rows = {c["name"]: c for c in data["coin_list"]}
        self.assertEqual(len(rows), 2)
        # Priced bitcoin: full allocation since it is the only valued holding.
        self.assertEqual(rows["Bitcoin"]["allocation_percentage"], Decimal("100"))
        # Unpriced ethereum: shown, no market values.
        self.assertIsNone(rows["Ethereum"]["market_value"])
        self.assertIsNone(rows["Ethereum"]["allocation_percentage"])
        # ETH cost basis is present on its row but excluded from totals.
        self.assertEqual(rows["Ethereum"]["cost_basis"], Decimal("3000"))

        metrics = data["portfolio_metrics"]
        self.assertEqual(metrics["total_invested"], Decimal("20000"))
        self.assertEqual(metrics["portfolio_value"], Decimal("30000"))
        self.assertEqual(metrics["portfolio_upl"], Decimal("10000"))
        self.assertEqual(metrics["unpriced_count"], 1)

    def test_zero_prices_do_not_divide_by_zero(self):
        # 11.5: a coin PRESENT in the market payload with current_price == 0 is a
        # real value (not missing), so it stays on the priced path: market_value 0,
        # a full unrealized loss, included in totals. When it's the only holding,
        # portfolio_value == 0, so allocation is 0/0 — guarded to 0% (not "-",
        # which is reserved for unpriced rows).
        market = [make_market_coin("bitcoin", current_price=0.0)]
        with patch("portfolio.services.get_coin_list_with_market", return_value=market):
            data = get_portfolio_overview_data(self.user, self.map)

        coin = data["coin_list"][0]
        self.assertEqual(coin["price"], Decimal("0"))
        self.assertEqual(coin["market_value"], Decimal("0"))
        self.assertEqual(coin["upl"], Decimal("-20000"))
        self.assertEqual(coin["upl_percentage"], Decimal("-100"))
        self.assertEqual(coin["allocation_percentage"], Decimal("0"))

        metrics = data["portfolio_metrics"]
        self.assertEqual(metrics["total_invested"], Decimal("20000"))
        self.assertEqual(metrics["portfolio_value"], Decimal("0"))
        self.assertEqual(metrics["portfolio_upl"], Decimal("-20000"))
        self.assertEqual(metrics["portfolio_upl_percentage"], Decimal("-100"))
        self.assertEqual(metrics["unpriced_count"], 0)  # priced, not unpriced


# ---------------------------------------------------------------------------
# 2.5 — create / edit / delete workflows (current correct behavior)
# ---------------------------------------------------------------------------
class TransactionWorkflowTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="wf", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.client.login(username="wf", password="pass")

    def _balance(self):
        return PortfolioTransaction.get_coin_balance(self.user, self.coin)

    def test_create_buy_by_coin_id(self):
        url = reverse("portfolio:add_transaction", args=[self.coin.id])
        response = self.client.post(
            url, {"type": "buy", "amount": "2", "price": "10000"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._balance(), Decimal("2"))

    def test_create_buy_by_cg_id(self):
        url = reverse("portfolio:add_transaction_cg", args=[self.coin.cg_id])
        response = self.client.post(
            url, {"type": "buy", "amount": "1", "price": "9000"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._balance(), Decimal("1"))

    def test_edit_transaction_updates_values(self):
        tx = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        url = reverse("portfolio:edit_transaction", args=[self.coin.id, tx.id])
        # GET renders the bound form
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(
            url, {"type": "buy", "amount": "5", "price": "11000"}
        )
        self.assertEqual(response.status_code, 302)
        tx.refresh_from_db()
        self.assertEqual(tx.amount, Decimal("5"))
        self.assertEqual(tx.price, Decimal("11000"))

    def test_create_transaction_honors_safe_next(self):
        target = (
            reverse("portfolio:all_transactions") + "?page=1&sort=price&direction=asc"
        )
        url = reverse("portfolio:add_transaction", args=[self.coin.id])
        response = self.client.post(
            url,
            {"type": "buy", "amount": "1", "price": "9000", "next": target},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, target)

    def test_create_transaction_ignores_unsafe_next(self):
        url = reverse("portfolio:add_transaction", args=[self.coin.id])
        response = self.client.post(
            url,
            {
                "type": "buy",
                "amount": "1",
                "price": "9000",
                "next": "https://evil.example/",
            },
        )
        self.assertRedirects(
            response,
            expected_url=reverse("portfolio:add_transaction", args=[self.coin.id]),
            fetch_redirect_response=False,
        )

    def test_edit_transaction_honors_safe_next(self):
        tx = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        target = (
            reverse("portfolio:all_transactions") + "?page=1&sort=price&direction=asc"
        )
        url = reverse("portfolio:edit_transaction", args=[self.coin.id, tx.id])
        response = self.client.post(
            url,
            {"type": "buy", "amount": "5", "price": "11000", "next": target},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, target)

    def test_delete_transaction_removes_row(self):
        tx = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        url = reverse("portfolio:delete_transaction", args=[self.coin.id, tx.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PortfolioTransaction.objects.filter(pk=tx.pk).exists())

    def test_coin_transaction_page_empty_state_is_coin_specific(self):
        empty_coin = Coin.objects.create(
            cg_id="litecoin", name="Litecoin", symbol="LTC"
        )
        url = reverse("portfolio:add_transaction", args=[empty_coin.id])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No transactions for Litecoin yet.")
        self.assertNotContains(response, "Your portfolio is empty.")

    def test_oversell_on_existing_balance_is_rejected(self):
        # This path IS handled today: selling more than the current balance is
        # rejected with a form error and no sell row is saved.
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        url = reverse("portfolio:add_transaction", args=[self.coin.id])
        with self.assertLogs("portfolio.views", level="WARNING") as logs:
            response = self.client.post(
                url, {"type": "sell", "amount": "3", "price": "12000"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Insufficient balance")
        self.assertFalse(
            PortfolioTransaction.objects.filter(coin=self.coin, type="sell").exists()
        )
        self.assertIn("operation=create", logs.output[0])
        self.assertIn(f"user_id={self.user.id}", logs.output[0])
        self.assertIn(f"coin_id={self.coin.id}", logs.output[0])
        self.assertIn("reason=Insufficient balance", logs.output[0])


# ---------------------------------------------------------------------------
# 2.5 — ledger-validation regression coverage
# ---------------------------------------------------------------------------
class TransactionValidationBugsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="val", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.client.login(username="val", password="pass")

    def _add_url(self):
        return reverse("portfolio:add_transaction", args=[self.coin.id])

    def test_get_coin_balance_zero_for_no_rows(self):
        # get_coin_balance() coalesces an empty aggregate to Decimal("0") (step
        # 10.2), so a user/coin with no transactions reports a zero balance.
        self.assertEqual(
            PortfolioTransaction.get_coin_balance(self.user, self.coin), Decimal("0")
        )

    def test_get_coin_balance_should_be_zero_not_none(self):
        # BUG (inspection/portfolio.md): get_coin_balance() returned None for a
        # user/coin with no transactions, which broke first-sell validation.
        # Step 10.2 returns Decimal("0").
        self.assertEqual(
            PortfolioTransaction.get_coin_balance(self.user, self.coin), Decimal("0")
        )

    def test_first_transaction_sell_is_rejected_gracefully(self):
        # BUG (inspection/portfolio.md): first tx being a sell → balance is None →
        # `amount > None` raises TypeError (500). Steps 10.2/10.4 should reject it
        # gracefully with a form error instead of crashing.
        response = self.client.post(
            self._add_url(), {"type": "sell", "amount": "1", "price": "12000"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PortfolioTransaction.objects.filter(coin=self.coin).exists())

    def test_negative_amount_is_rejected(self):
        # BUG (inspection/portfolio.md): the bare ModelForm accepts negative
        # amounts. Step 10.1 should validate amount > 0.
        self.client.post(
            self._add_url(), {"type": "buy", "amount": "-1", "price": "10000"}
        )
        self.assertEqual(PortfolioTransaction.objects.filter(coin=self.coin).count(), 0)

    def test_zero_amount_is_rejected(self):
        # BUG (inspection/portfolio.md): zero amount accepted. Step 10.1.
        self.client.post(
            self._add_url(), {"type": "buy", "amount": "0", "price": "10000"}
        )
        self.assertEqual(PortfolioTransaction.objects.filter(coin=self.coin).count(), 0)

    def test_zero_price_is_rejected(self):
        # BUG (inspection/portfolio.md): zero/negative price accepted. Step 10.1.
        self.client.post(self._add_url(), {"type": "buy", "amount": "1", "price": "0"})
        self.assertEqual(PortfolioTransaction.objects.filter(coin=self.coin).count(), 0)

    def test_sell_edit_is_edit_aware(self):
        # BUG (inspection/portfolio.md): editing a sell compares the new amount to
        # a balance that still includes the OLD sell, wrongly rejecting valid
        # edits. Step 10.4 should make sell validation edit-aware.
        # buy 5, sell 2 -> balance 3; editing the sell up to 4 is valid (bought 5).
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=5, price=10000
        )
        sell = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="sell", amount=2, price=12000
        )
        url = reverse("portfolio:edit_transaction", args=[self.coin.id, sell.id])
        self.client.post(url, {"type": "sell", "amount": "4", "price": "12000"})
        sell.refresh_from_db()
        self.assertEqual(sell.amount, Decimal("4"))

    def test_buy_edit_validated_against_later_sells(self):
        # BUG (inspection/portfolio.md): buy edits are not validated against later
        # sells, so a buy can be reduced below what was already sold, creating an
        # oversold ledger. Step 10.5 should reject such edits.
        # buy 5, sell 5 -> balance 0; editing the buy down to 3 must be rejected.
        buy = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=5, price=10000
        )
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="sell", amount=5, price=12000
        )
        url = reverse("portfolio:edit_transaction", args=[self.coin.id, buy.id])
        self.client.post(url, {"type": "buy", "amount": "3", "price": "10000"})
        buy.refresh_from_db()
        self.assertEqual(buy.amount, Decimal("5"))  # unchanged (edit rejected)


# ---------------------------------------------------------------------------
# 10.4 — edit-aware sell validation (regression coverage on the 10.3 replay)
# ---------------------------------------------------------------------------
class SellEditAwareTest(TestCase):
    """Locks in edit-aware sell validation delivered by the 10.3 replay.

    Editing a sell replaces that row in the projected timeline before the
    feasibility replay, so the old sell amount never double-counts. These tests
    drive the real form -> ledger service -> view path via the edit view and
    assert persisted state with ``refresh_from_db()``.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="sea", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.client.login(username="sea", password="pass")
        self.base = timezone.now()

    def _edit_url(self, tx):
        return reverse("portfolio:edit_transaction", args=[self.coin.id, tx.id])

    def _balance(self):
        return PortfolioTransaction.get_coin_balance(self.user, self.coin)

    def test_edit_sell_down_is_accepted(self):
        # buy 5, sell 4 -> balance 1; editing the sell DOWN to 2 stays feasible
        # (5 - 2 = 3) and is accepted.
        _make_tx(self.user, self.coin, "buy", 5, 10000, created=self.base)
        sell = _make_tx(
            self.user,
            self.coin,
            "sell",
            4,
            12000,
            created=self.base + timedelta(hours=1),
        )
        response = self.client.post(
            self._edit_url(sell), {"type": "sell", "amount": "2", "price": "12000"}
        )
        self.assertEqual(response.status_code, 302)
        sell.refresh_from_db()
        self.assertEqual(sell.amount, Decimal("2"))
        self.assertEqual(self._balance(), Decimal("3"))

    def test_edit_sell_up_to_infeasible_is_rejected(self):
        # buy 5, sell 2 -> balance 3; editing the sell UP to 6 oversells (5 - 6 =
        # -1). Rejected with a form error on `amount`, the row unchanged, HTTP 200.
        _make_tx(self.user, self.coin, "buy", 5, 10000, created=self.base)
        sell = _make_tx(
            self.user,
            self.coin,
            "sell",
            2,
            12000,
            created=self.base + timedelta(hours=1),
        )
        response = self.client.post(
            self._edit_url(sell), {"type": "sell", "amount": "6", "price": "12000"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Insufficient balance")
        self.assertIn("amount", response.context["form"].errors)
        sell.refresh_from_db()
        self.assertEqual(sell.amount, Decimal("2"))  # unchanged (edit rejected)
        self.assertEqual(self._balance(), Decimal("3"))

    def test_edit_first_sell_up_replays_before_later_sell(self):
        # Timeline ordering matters: buy 10 @t0, sell 3 @t1, sell 3 @t2.
        # Editing the FIRST sell up to 8 replays 10 - 8 = 2, then - 3 = -1, which
        # goes negative mid-history even though the naive final balance
        # (10 - 8 - 3 = -1) would too; the point is the replay rejects and the
        # first sell stays 3.
        _make_tx(self.user, self.coin, "buy", 10, 10000, created=self.base)
        first_sell = _make_tx(
            self.user,
            self.coin,
            "sell",
            3,
            12000,
            created=self.base + timedelta(hours=1),
        )
        _make_tx(
            self.user,
            self.coin,
            "sell",
            3,
            12000,
            created=self.base + timedelta(hours=2),
        )
        response = self.client.post(
            self._edit_url(first_sell),
            {"type": "sell", "amount": "8", "price": "12000"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Insufficient balance")
        self.assertIn("amount", response.context["form"].errors)
        first_sell.refresh_from_db()
        self.assertEqual(first_sell.amount, Decimal("3"))  # unchanged


# ---------------------------------------------------------------------------
# 10.5 — buy edits/deletes validated against later sells (replay, not final
# balance)
# ---------------------------------------------------------------------------
class BuyEditDeleteVsLaterSellsTest(TestCase):
    """Locks in buy-edit and buy-delete validation via the 10.3 feasibility replay.

    A buy cannot be reduced (edit) or removed (delete) below what later sells
    already consumed, because the replay projects the change onto the full
    ``(trade_date, id)``-ordered history and rejects the instant the running
    balance goes negative -- at ANY point, not merely at the final balance.
    These tests drive the real views (edit = POST ``portfolio:edit_transaction``;
    delete = POST ``portfolio:delete_transaction``) and assert persisted state.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="bevls", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.client.login(username="bevls", password="pass")
        self.base = timezone.now()

    def _edit_url(self, tx):
        return reverse("portfolio:edit_transaction", args=[self.coin.id, tx.id])

    def _delete_url(self, tx):
        return reverse("portfolio:delete_transaction", args=[self.coin.id, tx.id])

    def test_buy_edit_down_still_feasible_is_accepted(self):
        # buy 5 @t0, sell 2 @t1 -> editing the buy DOWN to 4 replays 4 - 2 = 2
        # (>= 0 throughout) and is accepted; the buy row now holds 4.
        buy = _make_tx(self.user, self.coin, "buy", 5, 10000, created=self.base)
        _make_tx(
            self.user,
            self.coin,
            "sell",
            2,
            12000,
            created=self.base + timedelta(hours=1),
        )
        response = self.client.post(
            self._edit_url(buy), {"type": "buy", "amount": "4", "price": "10000"}
        )
        self.assertEqual(response.status_code, 302)
        buy.refresh_from_db()
        self.assertEqual(buy.amount, Decimal("4"))

    def test_buy_delete_a_later_sell_depended_on_is_rejected(self):
        # buy 5 @t0, sell 5 @t1 -> deleting the buy leaves just the sell, replaying
        # to -5. Rejected via a messages error; the delete view always redirects
        # (302) and the buy row must still exist.
        buy = _make_tx(self.user, self.coin, "buy", 5, 10000, created=self.base)
        _make_tx(
            self.user,
            self.coin,
            "sell",
            5,
            12000,
            created=self.base + timedelta(hours=1),
        )
        response = self.client.post(self._delete_url(buy))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PortfolioTransaction.objects.filter(pk=buy.pk).exists())
        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(msgs)  # an error message was added

    def test_buy_delete_rejected_even_when_final_balance_would_be_nonnegative(self):
        # THE key case: buy 5 @t0, sell 5 @t1, buy 5 @t2 (final balance 5).
        # Deleting the FIRST buy (@t0) replays: sell 5 -> -5 at t1 -> rejected,
        # EVEN THOUGH the post-deletion final balance (0) would be >= 0. Proves
        # the guard is a mid-history feasibility replay, not a final-balance check.
        first_buy = _make_tx(self.user, self.coin, "buy", 5, 10000, created=self.base)
        _make_tx(
            self.user,
            self.coin,
            "sell",
            5,
            12000,
            created=self.base + timedelta(hours=1),
        )
        _make_tx(
            self.user,
            self.coin,
            "buy",
            5,
            10000,
            created=self.base + timedelta(hours=2),
        )
        response = self.client.post(self._delete_url(first_buy))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PortfolioTransaction.objects.filter(pk=first_buy.pk).exists())

    def test_buy_edit_down_rejected_even_when_final_balance_would_be_nonnegative(self):
        # Mirror of the delete case for edits: buy 5 @t0, sell 5 @t1, buy 5 @t2.
        # Editing the FIRST buy DOWN to 3 replays 3 -> -2 at t1 -> rejected even
        # though the final balance (3 - 5 + 5 = 3) would be >= 0. Form error on
        # `amount`, HTTP 200, the buy row unchanged.
        first_buy = _make_tx(self.user, self.coin, "buy", 5, 10000, created=self.base)
        _make_tx(
            self.user,
            self.coin,
            "sell",
            5,
            12000,
            created=self.base + timedelta(hours=1),
        )
        _make_tx(
            self.user,
            self.coin,
            "buy",
            5,
            10000,
            created=self.base + timedelta(hours=2),
        )
        response = self.client.post(
            self._edit_url(first_buy), {"type": "buy", "amount": "3", "price": "10000"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Insufficient balance")
        self.assertIn("amount", response.context["form"].errors)
        first_buy.refresh_from_db()
        self.assertEqual(first_buy.amount, Decimal("5"))  # unchanged (edit rejected)


# ---------------------------------------------------------------------------
# 2.5 — transaction list pagination (high page number)
# ---------------------------------------------------------------------------
class TransactionPaginationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pg", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        for _ in range(2):
            PortfolioTransaction.objects.create(
                user=self.user, coin=self.coin, type="buy", amount=1, price=10000
            )
        self.client.login(username="pg", password="pass")

    def test_all_transactions_high_page_does_not_raise(self):
        response = self.client.get(reverse("portfolio:all_transactions") + "?page=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 1)
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 1)
        self.assertNotContains(response, "Back to Market")

    def test_coin_transactions_high_page_does_not_raise(self):
        response = self.client.get(
            reverse("portfolio:add_transaction", args=[self.coin.id]) + "?page=2"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 1)
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 1)


# ---------------------------------------------------------------------------
# 2.5 — delete-path bugs
# ---------------------------------------------------------------------------
class DeletePathTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="del", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.client.login(username="del", password="pass")

    def test_all_transactions_delete_next_preserves_normalized_query_state(self):
        for index in range(11):
            PortfolioTransaction.objects.create(
                user=self.user,
                coin=self.coin,
                type="buy",
                amount=1,
                price=10000 + index,
            )

        query = "?page=2&sort=price&direction=asc&ignored=1"
        response = self.client.get(reverse("portfolio:all_transactions") + query)

        expected_next = (
            reverse("portfolio:all_transactions")
            + "?page=2&amp;sort=price&amp;direction=asc"
        )
        self.assertContains(response, f'value="{expected_next}"')
        self.assertContains(
            response,
            "?next=/portfolio/all/%3Fpage%3D2%26sort%3Dprice%26direction%3Dasc",
        )
        self.assertNotContains(response, "ignored=1")

    def test_delete_get_renders_confirmation_without_deleting(self):
        tx = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        target = (
            reverse("portfolio:all_transactions") + "?page=2&sort=price&direction=asc"
        )
        url = reverse("portfolio:delete_transaction", args=[self.coin.id, tx.id])

        response = self.client.get(url, {"next": target})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "portfolio/confirm_delete_transaction.html")
        self.assertContains(response, "Delete this buy transaction for Bitcoin?")
        self.assertContains(response, "Delete transaction")
        self.assertContains(
            response,
            f'value="{reverse("portfolio:all_transactions")}'
            "?page=2&amp;sort=price&amp;direction=asc"
            '"',
        )
        self.assertTrue(PortfolioTransaction.objects.filter(pk=tx.pk).exists())

    def test_delete_get_ignores_unsafe_next(self):
        tx = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        url = reverse("portfolio:delete_transaction", args=[self.coin.id, tx.id])

        response = self.client.get(url, {"next": "https://evil.example/"})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "https://evil.example/")
        self.assertContains(
            response,
            f'href="{reverse("portfolio:add_transaction", args=[self.coin.id])}"',
        )

    def test_valid_local_next_is_honored(self):
        tx = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        target = (
            reverse("portfolio:all_transactions") + "?page=2&sort=price&direction=asc"
        )
        url = reverse("portfolio:delete_transaction", args=[self.coin.id, tx.id])
        response = self.client.post(url, {"next": target})
        self.assertEqual(response.status_code, 302)
        # Assert the redirect actually lands on the requested target, not just
        # that it is safe: a regression that ignored `next` and fell back to
        # portfolio/views.py:160 (add_transaction) would also be "safe".
        self.assertEqual(response.url, target)
        self.assertTrue(url_has_allowed_host_and_scheme(response.url, {"testserver"}))

    def test_delete_buy_message_names_buy(self):
        # BUG (inspection/portfolio.md): deleting a buy that would make the balance
        # negative was guarded, but the message text said "sell transaction".
        # Step 10.7 fixed the wording so it names a buy.
        buy = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="sell", amount=1, price=12000
        )
        url = reverse("portfolio:delete_transaction", args=[self.coin.id, buy.id])
        response = self.client.post(url)
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("buy" in m.lower() for m in messages))

    def test_delete_unsafe_next_is_rejected(self):
        unsafe_values = [
            "https://evil.example/",
            "//evil.example/",
            r"https:\evil.example\phishing",
            r"\\evil.example\phishing",
        ]
        for unsafe in unsafe_values:
            with self.subTest(next=unsafe):
                tx = PortfolioTransaction.objects.create(
                    user=self.user, coin=self.coin, type="buy", amount=2, price=10000
                )
                url = reverse(
                    "portfolio:delete_transaction", args=[self.coin.id, tx.id]
                )
                response = self.client.post(url, {"next": unsafe})
                self.assertRedirects(
                    response,
                    expected_url=reverse(
                        "portfolio:add_transaction", args=[self.coin.id]
                    ),
                    fetch_redirect_response=False,
                )


class LedgerLockingTest(TestCase):
    """10.6 -- the mutation path must request a row-scoped ``FOR UPDATE`` lock.

    A normal ``TestCase`` is correct here: ``select_for_update`` emits its
    ``FOR UPDATE`` SQL inside the test's surrounding transaction. Concurrency
    itself is intentionally not tested (a threaded test is flaky); we only prove
    the lock is requested and scoped to ``PortfolioTransaction``.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=5, price=10000
        )

    def test_create_requests_row_scoped_lock(self):
        from portfolio.ledger import create_transaction

        with CaptureQueriesContext(connection) as ctx:
            create_transaction(
                user=self.user,
                coin=self.coin,
                type="buy",
                amount=Decimal("1"),
                price=Decimal("10000"),
            )
        sql = " ".join(q["sql"].lower() for q in ctx.captured_queries)
        self.assertIn("for update of", sql)


# ---------------------------------------------------------------------------
# 11.6 — delisted (is_active=False) coins: visible read-only + closable,
# but no new/increased buys (Option C).
# ---------------------------------------------------------------------------
class DelistedCoinTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dl", password="pass")
        # A coin the user holds that is later delisted from CoinGecko.
        self.coin = Coin.objects.create(
            cg_id="deadcoin", name="Dead Coin", symbol="DEAD", is_active=False
        )
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=100
        )
        self.client.login(username="dl", password="pass")

    def _add_url(self):
        return reverse("portfolio:add_transaction", args=[self.coin.id])

    # (a) overview: shown unpriced + badged, excluded from totals -----------
    def test_inactive_holding_shown_unpriced_and_badged(self):
        id_map = {self.coin.cg_id: self.coin.id}
        # A delisted coin is absent from the market payload.
        with patch("portfolio.services.get_coin_list_with_market", return_value=[]):
            data = get_portfolio_overview_data(self.user, id_map)
        self.assertEqual(len(data["coin_list"]), 1)
        row = data["coin_list"][0]
        # Ledger facts survive; row is flagged delisted; market fields are None.
        self.assertFalse(row["is_active"])
        self.assertEqual(row["amount"], Decimal("2"))
        self.assertEqual(row["cost_basis"], Decimal("200"))
        self.assertIsNone(row["price"])
        self.assertIsNone(row["market_value"])
        # Excluded from totals, counted as unpriced.
        metrics = data["portfolio_metrics"]
        self.assertEqual(metrics["portfolio_value"], 0)
        self.assertEqual(metrics["unpriced_count"], 1)

    def test_overview_renders_delisted_badge(self):
        with patch("portfolio.services.get_coin_list_with_market", return_value=[]):
            response = self.client.get(reverse("portfolio:overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delisted")

    # (b) all-transactions: inactive-coin rows appear -----------------------
    def test_inactive_coin_transactions_appear_in_all_transactions(self):
        txs = PortfolioTransaction.get_for_user(self.user)
        self.assertEqual(txs.count(), 1)
        response = self.client.get(reverse("portfolio:all_transactions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dead Coin")
        self.assertContains(response, "Delisted")

    # (f) per-coin page renders 200 for an inactive coin --------------------
    def test_per_coin_page_renders_for_inactive_coin(self):
        response = self.client.get(self._add_url())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "portfolio/create_transaction.html")
        self.assertContains(response, "Dead Coin")

    # (c) new buy blocked (create AND edit-to-buy) --------------------------
    def test_new_buy_on_inactive_coin_is_blocked(self):
        response = self.client.post(
            self._add_url(), {"type": "buy", "amount": "1", "price": "100"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "delisted")
        self.assertFalse(
            PortfolioTransaction.objects.filter(
                coin=self.coin, type="buy", amount=1
            ).exists()
        )

    def test_edit_sell_to_buy_on_inactive_coin_is_blocked(self):
        # Give the user a sell to edit (buy 2 already exists -> balance 2).
        sell = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="sell", amount=1, price=120
        )
        url = reverse("portfolio:edit_transaction", args=[self.coin.id, sell.id])
        response = self.client.post(url, {"type": "buy", "amount": "1", "price": "120"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "delisted")
        sell.refresh_from_db()
        self.assertEqual(sell.type, "sell")

    def test_increase_existing_buy_on_inactive_coin_is_blocked(self):
        tx = PortfolioTransaction.objects.get(coin=self.coin, type="buy")
        url = reverse("portfolio:edit_transaction", args=[self.coin.id, tx.id])
        response = self.client.post(url, {"type": "buy", "amount": "5", "price": "100"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "delisted")
        tx.refresh_from_db()
        self.assertEqual(tx.amount, Decimal("2"))

    # ALLOW: price-only / reducing edits of an existing buy -----------------
    def test_reduce_or_reprice_existing_buy_on_inactive_coin_is_allowed(self):
        tx = PortfolioTransaction.objects.get(coin=self.coin, type="buy")
        url = reverse("portfolio:edit_transaction", args=[self.coin.id, tx.id])
        # Same amount, new price (correction) -> allowed.
        response = self.client.post(url, {"type": "buy", "amount": "2", "price": "150"})
        self.assertEqual(response.status_code, 302)
        tx.refresh_from_db()
        self.assertEqual(tx.price, Decimal("150"))
        self.assertEqual(tx.amount, Decimal("2"))

    # (d) sell allowed and closes the position ------------------------------
    def test_sell_on_inactive_coin_closes_position(self):
        response = self.client.post(
            self._add_url(), {"type": "sell", "amount": "2", "price": "80"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            PortfolioTransaction.get_coin_balance(self.user, self.coin), Decimal("0")
        )
        # A fully-closed delisted position drops off the overview map.
        ids = PortfolioTransaction.get_positive_coin_balance_ids(self.user)
        self.assertNotIn(self.coin.id, [item["coin_id"] for item in ids])

    # (e) delete allowed ----------------------------------------------------
    def test_delete_transaction_on_inactive_coin_is_allowed(self):
        tx = PortfolioTransaction.objects.get(coin=self.coin, type="buy")
        url = reverse("portfolio:delete_transaction", args=[self.coin.id, tx.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PortfolioTransaction.objects.filter(pk=tx.pk).exists())

    # model/ledger reads see the delisted ledger ----------------------------
    def test_get_coin_balance_counts_inactive_coin(self):
        self.assertEqual(
            PortfolioTransaction.get_coin_balance(self.user, self.coin), Decimal("2")
        )

    def test_sell_feasibility_uses_real_inactive_ledger(self):
        # Selling more than held on a delisted coin is still rejected via replay.
        response = self.client.post(
            self._add_url(), {"type": "sell", "amount": "3", "price": "80"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Insufficient balance")
        self.assertFalse(
            PortfolioTransaction.objects.filter(coin=self.coin, type="sell").exists()
        )


# ---------------------------------------------------------------------------
# 11.7 — user-entered trade_date (date-only; ledger order key)
# ---------------------------------------------------------------------------
class TradeDateTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="td", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.client.login(username="td", password="pass")

    def _add_url(self):
        return reverse("portfolio:add_transaction", args=[self.coin.id])

    def test_model_default_fills_trade_date_today(self):
        # A row created without an explicit trade_date gets today's date (the
        # model default) -- mirrors what the backfill guarantees for old rows.
        tx = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=1, price=100
        )
        self.assertEqual(tx.trade_date, timezone.localdate())

    def test_create_form_persists_trade_date(self):
        past = timezone.localdate() - timedelta(days=10)
        response = self.client.post(
            self._add_url(),
            {
                "type": "buy",
                "amount": "2",
                "price": "10000",
                "trade_date": past.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        tx = PortfolioTransaction.objects.get(user=self.user, coin=self.coin)
        self.assertEqual(tx.trade_date, past)

    def test_trade_date_renders_in_transaction_list(self):
        past = timezone.localdate() - timedelta(days=5)
        _make_tx(self.user, self.coin, "buy", 1, 100)
        PortfolioTransaction.objects.filter(user=self.user).update(trade_date=past)
        response = self.client.get(self._add_url())
        self.assertContains(response, past.strftime("%b %d, %Y"))

    def test_future_trade_date_is_rejected(self):
        future = timezone.localdate() + timedelta(days=1)
        response = self.client.post(
            self._add_url(),
            {
                "type": "buy",
                "amount": "1",
                "price": "100",
                "trade_date": future.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Trade date cannot be in the future.")
        self.assertFalse(PortfolioTransaction.objects.filter(user=self.user).exists())

    def test_unbound_create_form_defaults_to_today(self):
        form = PortfolioTransactionForm()
        self.assertEqual(form.fields["trade_date"].initial, timezone.localdate())

    def test_omitted_trade_date_falls_back_to_today(self):
        # A bare buy/sell POST (no trade_date) still works and defaults to today.
        response = self.client.post(
            self._add_url(), {"type": "buy", "amount": "1", "price": "100"}
        )
        self.assertEqual(response.status_code, 302)
        tx = PortfolioTransaction.objects.get(user=self.user, coin=self.coin)
        self.assertEqual(tx.trade_date, timezone.localdate())

    def test_edit_form_shows_and_updates_trade_date(self):
        tx = _make_tx(self.user, self.coin, "buy", 2, 10000)
        url = reverse("portfolio:edit_transaction", args=[self.coin.id, tx.id])
        # Existing value is rendered on the edit form.
        self.assertContains(self.client.get(url), timezone.localdate().isoformat())
        new_date = timezone.localdate() - timedelta(days=3)
        response = self.client.post(
            url,
            {
                "type": "buy",
                "amount": "2",
                "price": "10000",
                "trade_date": new_date.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        tx.refresh_from_db()
        self.assertEqual(tx.trade_date, new_date)

    def test_migration_backfill_uses_created_date(self):
        # Exercise the 0004 data migration's backfill directly: a row whose
        # trade_date is NULL is filled from the local date of `created`, not
        # today -- so historical trade dates reflect each row's created date.
        import importlib

        mig = importlib.import_module(
            "portfolio.migrations.0004_portfoliotransaction_trade_date"
        )

        # The test DB already has the migrated (non-null) schema, so we can't
        # insert a NULL trade_date. Instead give the row today's default and
        # confirm the backfill overwrites it with the local date of `created`.
        created_at = timezone.now() - timedelta(days=400)
        tx = _make_tx(self.user, self.coin, "buy", 1, 100, created=created_at)
        self.assertEqual(tx.trade_date, timezone.localdate())

        class _Apps:
            def get_model(self, app_label, model_name):
                return PortfolioTransaction

        mig.backfill_trade_date_from_created(_Apps(), None)
        tx.refresh_from_db()
        self.assertEqual(tx.trade_date, timezone.localtime(created_at).date())
        self.assertNotEqual(tx.trade_date, timezone.localdate())


class TradeDateLedgerOrderingTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tdledger", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.base_date = timezone.localdate() - timedelta(days=10)

    def test_create_sell_before_buy_trade_date_is_rejected(self):
        _make_tx(
            self.user,
            self.coin,
            "buy",
            1,
            10000,
            trade_date=self.base_date + timedelta(days=1),
        )

        with self.assertRaisesMessage(LedgerError, "Insufficient balance"):
            create_transaction(
                user=self.user,
                coin=self.coin,
                type="sell",
                amount=Decimal("1"),
                price=Decimal("12000"),
                trade_date=self.base_date,
            )

        self.assertFalse(
            PortfolioTransaction.objects.filter(user=self.user, type="sell").exists()
        )

    def test_edit_buy_after_existing_sell_is_rejected(self):
        buy = _make_tx(
            self.user,
            self.coin,
            "buy",
            1,
            10000,
            trade_date=self.base_date,
        )
        _make_tx(
            self.user,
            self.coin,
            "sell",
            1,
            12000,
            trade_date=self.base_date + timedelta(days=1),
        )

        with self.assertRaisesMessage(LedgerError, "Insufficient balance"):
            update_transaction(
                transaction=buy,
                type="buy",
                amount=Decimal("1"),
                price=Decimal("10000"),
                trade_date=self.base_date + timedelta(days=2),
            )

        buy.refresh_from_db()
        self.assertEqual(buy.trade_date, self.base_date)
