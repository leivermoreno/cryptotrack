import unittest
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
from portfolio.services import build_holdings, get_portfolio_overview_data

from .models import PortfolioTransaction

User = get_user_model()


def _make_tx(user, coin, type, amount, price, created=None):
    """Create a transaction, optionally forcing the auto_now_add ``created``."""
    tx = PortfolioTransaction.objects.create(
        user=user, coin=coin, type=type, amount=amount, price=price
    )
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
        self.assertContains(response, "No coins in your portfolio yet.")
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
            "Market data is temporarily unavailable. Please try again shortly.",
        )
        # No P/L summary metric keys were populated.
        self.assertNotIn("portfolio_value", response.context)


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
        # Two buys share the exact same ``created`` timestamp; FIFO must consume
        # the earlier-inserted (lower-id) lot first. Without the ``id`` tiebreak
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

    @unittest.expectedFailure
    def test_oversold_history_does_not_crash(self):
        # BUG (inspection/portfolio.md, "Service concerns"): a sell before enough
        # buy lots makes holdings[...][0] raise IndexError. Step 11.1 should make
        # build_holdings fail gracefully / return a domain error instead.
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
        self.assertEqual(coin["value"], Decimal("20000"))  # cost basis
        self.assertEqual(coin["avg_buy_price"], Decimal("10000"))
        self.assertEqual(coin["price"], Decimal("15000"))
        self.assertEqual(coin["upl"], Decimal("10000"))
        self.assertEqual(coin["upl_percentage"], Decimal("50"))
        self.assertEqual(coin["allocation_percentage"], Decimal("100"))
        metrics = data["portfolio_metrics"]
        self.assertEqual(metrics["total_invested"], Decimal("20000"))
        self.assertEqual(metrics["portfolio_value"], Decimal("30000"))
        self.assertEqual(metrics["portfolio_upl"], Decimal("10000"))

    def test_holding_missing_from_market_is_dropped(self):
        # CURRENT behavior: a positive-balance coin absent from the market
        # response silently disappears from the overview. Step 11.4 should stop
        # dropping holdings silently; characterized green here as today's contract.
        with patch("portfolio.services.get_coin_list_with_market", return_value=[]):
            data = get_portfolio_overview_data(self.user, self.map)
        self.assertEqual(data["coin_list"], [])

    @unittest.expectedFailure
    def test_zero_prices_do_not_divide_by_zero(self):
        # BUG (inspection/portfolio.md): allocation_percentage divides by
        # portfolio_value; if every current price is 0 the portfolio value is 0
        # and the division raises. Step 11.5 should guard against zero/unknown
        # prices.
        market = [make_market_coin("bitcoin", current_price=0.0)]
        with patch("portfolio.services.get_coin_list_with_market", return_value=market):
            data = get_portfolio_overview_data(self.user, self.map)
        self.assertIsInstance(data["coin_list"], list)


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

    def test_delete_transaction_removes_row(self):
        tx = PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        url = reverse("portfolio:delete_transaction", args=[self.coin.id, tx.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PortfolioTransaction.objects.filter(pk=tx.pk).exists())

    def test_oversell_on_existing_balance_is_rejected(self):
        # This path IS handled today: selling more than the current balance is
        # rejected with a form error and no sell row is saved.
        PortfolioTransaction.objects.create(
            user=self.user, coin=self.coin, type="buy", amount=2, price=10000
        )
        url = reverse("portfolio:add_transaction", args=[self.coin.id])
        response = self.client.post(
            url, {"type": "sell", "amount": "3", "price": "12000"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Insufficient balance")
        self.assertFalse(
            PortfolioTransaction.objects.filter(coin=self.coin, type="sell").exists()
        )


# ---------------------------------------------------------------------------
# 2.5 — known ledger-validation bugs (expected failures)
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

    Editing a sell replaces that row in its own ``(created, id)`` slot before
    the feasibility replay, so the old sell amount never double-counts. These
    tests drive the real form -> ledger service -> view path via the edit view
    and assert persisted state with ``refresh_from_db()``.
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
        # (created, id) ordering matters: buy 10 @t0, sell 3 @t1, sell 3 @t2.
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
    ``(created, id)``-ordered history and rejects the instant the running
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
        self.assertNotContains(response, "ignored=1")

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
