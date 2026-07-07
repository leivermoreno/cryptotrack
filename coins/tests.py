from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from coins.exceptions import (
    CoinGeckoResponseError,
    CoinGeckoUnavailableError,
)
from coins.management.commands.runapscheduler import (
    SUPPORTED_COINS_SYNC_INTERVAL_SECONDS,
    sync_supported_coins_job,
)
from coins.management.commands.runapscheduler import (
    Command as RunapschedulerCommand,
)
from coins.sync import SupportedCoinSyncResult, sync_supported_coins
from common.test_utils import make_market_coin, market_response

from .models import Coin, Watchlist

User = get_user_model()

# Single user-facing copy for a CoinGecko whole-call failure (5.6).
MARKET_UNAVAILABLE_COPY = (
    "Market data is temporarily unavailable. Please try again shortly."
)


class CoinModelTest(TestCase):
    def test_coin_creation_and_str(self):
        coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.assertEqual(str(coin), "Bitcoin")
        self.assertTrue(coin.is_active)


class WatchlistModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.coin = Coin.objects.create(cg_id="ethereum", name="Ethereum", symbol="ETH")

    def test_watchlist_creation_and_uniqueness(self):
        Watchlist.objects.create(user=self.user, coin=self.coin)
        with self.assertRaises(IntegrityError):
            Watchlist.objects.create(user=self.user, coin=self.coin)

    def test_get_coin_ids_for_user(self):
        Watchlist.objects.create(user=self.user, coin=self.coin)
        ids = list(Watchlist.get_coin_ids_for_user(self.user.id))
        self.assertIn(self.coin.cg_id, ids)

    def test_get_coin_ids_for_user_orders_by_insertion(self):
        # Rows added sequentially must come back in insertion order. Whether the
        # ``auto_now_add`` timestamps tie or advance, ``(created, id)`` collapses
        # to insertion order because ``id`` increases monotonically.
        coins = [
            Coin.objects.create(cg_id=f"coin-{i}", name=f"Coin {i}", symbol=f"C{i}")
            for i in range(5)
        ]
        for coin in coins:
            Watchlist.objects.create(user=self.user, coin=coin)

        ids = list(Watchlist.get_coin_ids_for_user(self.user.id))
        self.assertEqual(ids, [coin.cg_id for coin in coins])

    def test_get_coin_ids_for_user_created_dominates_id(self):
        # ``created`` is the primary sort key: when timestamps disagree with
        # insertion (id) order, the result follows ``created``, not ``id``.
        coins = [
            Coin.objects.create(cg_id=f"coin-{i}", name=f"Coin {i}", symbol=f"C{i}")
            for i in range(3)
        ]
        rows = [Watchlist.objects.create(user=self.user, coin=coin) for coin in coins]
        # Overwrite auto_now_add timestamps so newest-inserted sorts first.
        base = timezone.now()
        for offset, row in enumerate(reversed(rows)):
            Watchlist.objects.filter(pk=row.pk).update(
                created=base + timedelta(seconds=offset)
            )

        ids = list(Watchlist.get_coin_ids_for_user(self.user.id))
        self.assertEqual(ids, [coin.cg_id for coin in reversed(coins)])


class CoinsAdminSmokeTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pass"
        )
        self.user = User.objects.create_user(username="watcher", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.watchlist = Watchlist.objects.create(user=self.user, coin=self.coin)
        self.client.force_login(self.admin_user)

    def test_coin_admin_list_and_change_pages_load(self):
        response = self.client.get(reverse("admin:coins_coin_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bitcoin")

        response = self.client.get(
            reverse("admin:coins_coin_change", args=[self.coin.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "bitcoin")
        self.assertEqual(list(response.context["adminform"].form.fields), ["is_active"])

    def test_coin_admin_add_page_is_disabled(self):
        response = self.client.get(reverse("admin:coins_coin_add"))
        self.assertEqual(response.status_code, 403)

    def test_watchlist_admin_list_add_and_change_pages_load(self):
        response = self.client.get(reverse("admin:coins_watchlist_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "watcher")
        self.assertContains(response, "Bitcoin")

        response = self.client.get(reverse("admin:coins_watchlist_add"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add watchlist")

        response = self.client.get(
            reverse("admin:coins_watchlist_change", args=[self.watchlist.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "watcher")
        self.assertContains(response, "Bitcoin")


class CoinsViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        self.coin2 = Coin.objects.create(
            cg_id="ethereum", name="Ethereum", symbol="ETH"
        )

    @patch("coins.views.get_page_count", return_value=1)
    @patch(
        "coins.views.get_coin_list_with_market",
        return_value=market_response("bitcoin", "ethereum"),
    )
    def test_render_index_view(self, mock_market, mock_page_count):
        response = self.client.get(reverse("coins:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "coins/index.html")
        self.assertIn("coin_list", response.context)
        self.assertTrue(mock_market.called)
        coin_names = [c["name"] for c in response.context["coin_list"]]
        self.assertIn("Bitcoin", coin_names)

    @patch("coins.views.get_page_count", return_value=1)
    @patch("coins.views.get_coin_list_with_market", return_value=[])
    def test_render_index_empty_catalog(self, mock_market, mock_page_count):
        response = self.client.get(reverse("coins:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No coins are available right now.")
        self.assertContains(response, "Refresh")

    @patch(
        "coins.views.get_coin_list_with_market",
        return_value=market_response("bitcoin"),
    )
    def test_render_search_view(self, mock_market):
        response = self.client.get(reverse("coins:search") + "?search=Bitcoin")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "coins/search.html")
        self.assertIn("coin_list", response.context)
        self.assertTrue(mock_market.called)
        coin_names = [c["name"] for c in response.context["coin_list"]]
        self.assertIn("Bitcoin", coin_names)

    def test_render_search_empty_query_redirects(self):
        response = self.client.get(reverse("coins:search"))
        self.assertRedirects(
            response,
            expected_url=reverse("coins:index"),
            fetch_redirect_response=False,
        )

    def test_render_search_no_matches(self):
        response = self.client.get(reverse("coins:search"), {"search": "doesnotexist"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No active coins match "doesnotexist".')
        self.assertContains(response, "Clear search")

    def test_add_remove_to_watchlist_authenticated(self):
        # add
        self.client.login(username="testuser", password="pass")
        data = {"next": reverse("coins:watchlist")}
        url = reverse("coins:add_remove_to_watchlist", args=[self.coin.cg_id])
        response = self.client.post(url, data)
        self.assertRedirects(
            response,
            expected_url=reverse("coins:watchlist"),
            fetch_redirect_response=False,
        )
        self.assertTrue(
            Watchlist.objects.filter(user=self.user, coin=self.coin).exists()
        )
        # remove
        response = self.client.post(url, data)
        self.assertRedirects(
            response,
            expected_url=reverse("coins:watchlist"),
            fetch_redirect_response=False,
        )
        self.assertFalse(
            Watchlist.objects.filter(user=self.user, coin=self.coin).exists()
        )

    def test_add_remove_to_watchlist_invalid_coin(self):
        self.client.login(username="testuser", password="pass")
        url = reverse("coins:add_remove_to_watchlist", args=["invalidcgid"])
        response = self.client.post(url, {"next": reverse("coins:watchlist")})
        self.assertRedirects(
            response,
            expected_url=reverse("coins:watchlist"),
            fetch_redirect_response=False,
        )

    def test_add_remove_to_watchlist_unauthenticated(self):
        url = reverse("coins:add_remove_to_watchlist", args=[self.coin.cg_id])
        response = self.client.post(url)
        self.assertRedirects(
            response, expected_url=reverse("accounts:login", query={"next": url})
        )

    @patch(
        "coins.views.get_coin_list_with_market",
        return_value=market_response("bitcoin"),
    )
    def test_render_watchlist_authenticated(self, mock_market):
        Watchlist.objects.create(user=self.user, coin=self.coin)
        self.client.login(username="testuser", password="pass")
        response = self.client.get(reverse("coins:watchlist"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "coins/watchlist.html")
        self.assertIn("coin_list", response.context)
        self.assertTrue(mock_market.called)
        coin_names = [c["name"] for c in response.context["coin_list"]]
        self.assertIn("Bitcoin", coin_names)

    def test_render_watchlist_unauthenticated(self):
        url = reverse("coins:watchlist")
        response = self.client.get(url)
        self.assertRedirects(
            response, expected_url=reverse("accounts:login", query={"next": url})
        )

    def test_render_watchlist_empty(self):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(reverse("coins:watchlist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your watchlist is empty.")
        self.assertContains(response, "Browse market")

    @patch(
        "coins.views.get_coin_list_with_market",
        return_value=market_response("bitcoin"),
    )
    def test_render_watchlist_pagination_is_stable_across_boundary(self, mock_market):
        # WATCHLIST_COINS_PAGE == 10, so 15 rows straddle a page boundary. The
        # split between page 1 and page 2 must be deterministic and repeatable.
        from coins.settings import WATCHLIST_COINS_PAGE

        coins = [
            Coin.objects.create(cg_id=f"coin-{i}", name=f"Coin {i}", symbol=f"C{i}")
            for i in range(WATCHLIST_COINS_PAGE + 5)
        ]
        for coin in coins:
            Watchlist.objects.create(user=self.user, coin=coin)
        self.client.login(username="testuser", password="pass")

        url = reverse("coins:watchlist")

        def page_ids(page):
            response = self.client.get(url, {"page": page})
            self.assertEqual(response.status_code, 200)
            return list(response.context["page_obj"].object_list)

        page1_first = page_ids(1)
        page2_first = page_ids(2)
        page1_second = page_ids(1)
        page2_second = page_ids(2)

        # Repeated requests return the same split (no reshuffling).
        self.assertEqual(page1_first, page1_second)
        self.assertEqual(page2_first, page2_second)
        # The split follows insertion order and partitions the full set exactly.
        expected = [coin.cg_id for coin in coins]
        self.assertEqual(page1_first, expected[:WATCHLIST_COINS_PAGE])
        self.assertEqual(page2_first, expected[WATCHLIST_COINS_PAGE:])


# ---------------------------------------------------------------------------
# Subtask 2.4 additions: watchlist toggling, invalid ids, inactive coins,
# query preservation, and unsafe ``next`` values.
# Section 2 safety-net baseline: GREEN characterizations of current behavior.
# ---------------------------------------------------------------------------


class WatchlistToggleTest(TestCase):
    """GREEN characterization of watchlist toggling behavior."""

    def setUp(self):
        self.client = Client()
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")

    def test_fresh_toggle_add_creates_row_and_redirects_to_index_by_default(self):
        # With no ``next`` posted, a fresh toggle-add creates the row and
        # falls back to the market index redirect.
        user = User.objects.create_user(username="alice", password="pass")
        self.client.login(username="alice", password="pass")
        url = reverse("coins:add_remove_to_watchlist", args=[self.coin.cg_id])
        response = self.client.post(url)
        self.assertRedirects(
            response,
            expected_url=reverse("coins:index"),
            fetch_redirect_response=False,
        )
        self.assertTrue(Watchlist.objects.filter(user=user, coin=self.coin).exists())

    def test_two_users_keep_isolated_watchlists(self):
        # User-data isolation: two users toggling the same coin get independent
        # rows, and one user removing the coin does not affect the other.
        alice = User.objects.create_user(username="alice", password="pass")
        bob = User.objects.create_user(username="bob", password="pass")
        url = reverse("coins:add_remove_to_watchlist", args=[self.coin.cg_id])

        self.client.login(username="alice", password="pass")
        self.client.post(url)
        self.client.logout()

        self.client.login(username="bob", password="pass")
        self.client.post(url)
        self.client.logout()

        self.assertTrue(Watchlist.objects.filter(user=alice, coin=self.coin).exists())
        self.assertTrue(Watchlist.objects.filter(user=bob, coin=self.coin).exists())

        # Alice toggles off; Bob's row is untouched.
        self.client.login(username="alice", password="pass")
        self.client.post(url)
        self.client.logout()

        self.assertFalse(Watchlist.objects.filter(user=alice, coin=self.coin).exists())
        self.assertTrue(Watchlist.objects.filter(user=bob, coin=self.coin).exists())


class WatchlistInvalidCoinTest(TestCase):
    """GREEN: a nonexistent ``cg_id`` is silently ignored (Coin.DoesNotExist)."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="pass")

    def test_nonexistent_cg_id_creates_no_row_and_still_redirects(self):
        self.client.login(username="testuser", password="pass")
        url = reverse("coins:add_remove_to_watchlist", args=["does-not-exist"])
        response = self.client.post(url, {"next": reverse("coins:watchlist")})
        self.assertRedirects(
            response,
            expected_url=reverse("coins:watchlist"),
            fetch_redirect_response=False,
        )
        self.assertEqual(Watchlist.objects.count(), 0)


class InactiveCoinsTest(TestCase):
    """GREEN characterization of the current inactive-coin soft-hide behavior.

    NOTE: whether inactive coins SHOULD stay visible (rather than silently
    disappearing) is an open design decision (steps 11.6 / 12). These tests
    only pin down today's behavior; they are not asserting a desired end state.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.active = Coin.objects.create(
            cg_id="bitcoin", name="Bitcoin", symbol="BTC", is_active=True
        )
        self.inactive = Coin.objects.create(
            cg_id="deadcoin", name="Deadcoin", symbol="DEAD", is_active=False
        )

    def test_get_coin_ids_for_user_excludes_inactive(self):
        Watchlist.objects.create(user=self.user, coin=self.active)
        Watchlist.objects.create(user=self.user, coin=self.inactive)
        ids = list(Watchlist.get_coin_ids_for_user(self.user.id))
        self.assertIn(self.active.cg_id, ids)
        self.assertNotIn(self.inactive.cg_id, ids)

    def test_toggle_inactive_coin_is_silently_ignored(self):
        # The view filters ``is_active=True``, so an inactive coin raises
        # Coin.DoesNotExist -> no row change, still redirects.
        self.client.login(username="testuser", password="pass")
        url = reverse("coins:add_remove_to_watchlist", args=[self.inactive.cg_id])
        response = self.client.post(url, {"next": reverse("coins:watchlist")})
        self.assertRedirects(
            response,
            expected_url=reverse("coins:watchlist"),
            fetch_redirect_response=False,
        )
        self.assertFalse(
            Watchlist.objects.filter(user=self.user, coin=self.inactive).exists()
        )

    @patch(
        "coins.views.get_coin_list_with_market",
        return_value=market_response("bitcoin"),
    )
    def test_search_excludes_inactive_coins(self, mock_market):
        # Both coins' names match "coin"; only the active one's cg_id should
        # reach get_coin_list_with_market (the view filters is_active=True).
        active = Coin.objects.create(
            cg_id="supercoin", name="Super Coin", symbol="SUP", is_active=True
        )
        Coin.objects.create(
            cg_id="ghostcoin", name="Ghost Coin", symbol="GHO", is_active=False
        )
        response = self.client.get(reverse("coins:search") + "?search=Coin")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_market.called)
        ids = list(mock_market.call_args.kwargs["ids"])
        self.assertIn(active.cg_id, ids)
        self.assertNotIn("ghostcoin", ids)


class QueryPreservationTest(TestCase):
    """List pagination preserves intended query state."""

    def setUp(self):
        self.client = Client()

    @patch(
        "coins.views.get_coin_list_with_market",
        return_value=[make_market_coin(cg_id="preserve0", name="Preserve 0")],
    )
    def test_search_preserves_term_in_pagination_links(self, mock_market):
        # Create > RESULTS_PAGE (100) matching coins so a "next" pagination
        # link is rendered; the common partial passes send_search=True.
        Coin.objects.bulk_create(
            [
                Coin(cg_id=f"preserve{i}", name=f"Preserve {i}", symbol=f"PR{i}")
                for i in range(101)
            ]
        )
        response = self.client.get(
            reverse("coins:search")
            + "?search=Preserve&page=1&sort=price&direction=desc"
        )
        self.assertEqual(response.status_code, 200)
        # The rendered next-page link carries page, sort, direction and search.
        self.assertContains(
            response, "page=2&amp;sort=price&amp;direction=desc&amp;search=Preserve"
        )

    @patch(
        "coins.views.get_coin_list_with_market",
        return_value=[make_market_coin(cg_id="special0", name="Special Preserve 0")],
    )
    def test_search_state_with_reserved_chars_is_encoded_in_links_and_next(
        self, mock_market
    ):
        search = "Special Preserve & price=1?"
        Coin.objects.bulk_create(
            [
                Coin(cg_id=f"special{i}", name=f"{search} {i}", symbol=f"SP{i}")
                for i in range(101)
            ]
        )

        response = self.client.get(
            reverse(
                "coins:search",
                query={
                    "search": search,
                    "page": "1",
                    "sort": "price",
                    "direction": "desc",
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "page=2&amp;sort=price&amp;direction=desc&amp;"
            "search=Special+Preserve+%26+price%3D1%3F",
        )
        self.assertContains(
            response,
            'value="/search/?page=1&amp;sort=price&amp;direction=desc&amp;'
            'search=Special+Preserve+%26+price%3D1%3F"',
        )
        self.assertContains(
            response,
            "next=/search/%3Fpage%3D1%26sort%3Dprice%26direction%3Ddesc%26"
            "search%3DSpecial%2BPreserve%2B%2526%2Bprice%253D1%253F",
        )

    @patch("coins.views.get_page_count", return_value=3)
    @patch(
        "coins.views.get_coin_list_with_market",
        return_value=market_response("bitcoin"),
    )
    def test_index_pagination_preserves_sort_direction(
        self, mock_market, mock_page_count
    ):
        response = self.client.get(
            reverse("coins:index") + "?sort=price&direction=desc&page=1"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "page=2&amp;sort=price&amp;direction=desc")


class OpenRedirectTest(TestCase):
    """The ``next`` open-redirect (inspection/coins.md Key Risks #7). A valid
    local ``next`` is honored; external/protocol-relative values fall back to the
    safe default."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")

    def test_valid_local_next_is_honored(self):
        self.client.login(username="testuser", password="pass")
        url = reverse("coins:add_remove_to_watchlist", args=[self.coin.cg_id])
        target = reverse("coins:watchlist")
        response = self.client.post(url, {"next": target})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, target)

    def test_unsafe_next_is_rejected(self):
        self.client.login(username="testuser", password="pass")
        url = reverse("coins:add_remove_to_watchlist", args=[self.coin.cg_id])
        unsafe_values = [
            "https://evil.example/",
            "//evil.example/",
            r"https:\evil.example\phishing",
            r"\\evil.example\phishing",
        ]
        for unsafe in unsafe_values:
            with self.subTest(next=unsafe):
                response = self.client.post(url, {"next": unsafe})
                self.assertRedirects(
                    response,
                    expected_url=reverse("coins:index"),
                    fetch_redirect_response=False,
                )


# ---------------------------------------------------------------------------
# 5.6 — graceful fallbacks when the CoinGecko client raises CoinGeckoError.
# Each web surface should render its normal shell with an in-place banner and
# an empty table (HTTP 200, no 500); the scheduler should skip and not crash.
# Patches target the 5.5 delegator seam (where the names are looked up).
# ---------------------------------------------------------------------------
class CoinGeckoFallbackTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.coin = Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")

    @patch("coins.views.get_page_count", side_effect=CoinGeckoUnavailableError("down"))
    def test_index_page_count_failure_renders_banner(self, mock_page_count):
        response = self.client.get(reverse("coins:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "coins/index.html")
        self.assertTrue(response.context["market_unavailable"])
        self.assertEqual(response.context["coin_list"], [])
        self.assertContains(response, MARKET_UNAVAILABLE_COPY)
        self.assertNotContains(response, "No coins are available right now.")

    @patch("coins.views.get_page_count", return_value=1)
    @patch(
        "coins.views.get_coin_list_with_market",
        side_effect=CoinGeckoResponseError("malformed"),
    )
    def test_index_market_failure_renders_banner(self, mock_market, mock_page_count):
        response = self.client.get(reverse("coins:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["market_unavailable"])
        self.assertContains(response, MARKET_UNAVAILABLE_COPY)
        self.assertNotContains(response, "No coins are available right now.")

    @patch(
        "coins.views.get_coin_list_with_market",
        side_effect=CoinGeckoUnavailableError("down"),
    )
    def test_search_failure_renders_banner(self, mock_market):
        response = self.client.get(reverse("coins:search") + "?search=Bitcoin")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "coins/search.html")
        self.assertTrue(response.context["market_unavailable"])
        self.assertEqual(response.context["coin_list"], [])
        self.assertContains(response, MARKET_UNAVAILABLE_COPY)
        self.assertNotContains(response, "No active coins match")

    @patch(
        "coins.views.get_coin_list_with_market",
        side_effect=CoinGeckoUnavailableError("down"),
    )
    def test_watchlist_failure_renders_banner(self, mock_market):
        Watchlist.objects.create(user=self.user, coin=self.coin)
        self.client.login(username="testuser", password="pass")
        response = self.client.get(reverse("coins:watchlist"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "coins/watchlist.html")
        self.assertTrue(response.context["market_unavailable"])
        self.assertEqual(response.context["coin_list"], [])
        self.assertContains(response, MARKET_UNAVAILABLE_COPY)
        self.assertNotContains(response, "Your watchlist is empty.")


class SupportedCoinSyncTest(TestCase):
    @patch(
        "coins.sync.get_supported_coin_list",
        return_value=[
            {"id": "bitcoin", "name": "Bitcoin", "symbol": "btc"},
        ],
    )
    def test_sync_supported_coins_creates_missing_rows(self, mock_supported):
        result = sync_supported_coins()

        mock_supported.assert_called_once_with()
        self.assertEqual(
            result,
            SupportedCoinSyncResult(
                created=1, updated=0, deactivated=0, skipped=0, failed=0
            ),
        )
        self.assertEqual(Coin.objects.count(), 1)

        bitcoin = Coin.objects.get(cg_id="bitcoin")
        self.assertEqual(bitcoin.name, "Bitcoin")
        self.assertEqual(bitcoin.symbol, "btc")
        self.assertTrue(bitcoin.is_active)

    @patch(
        "coins.sync.get_supported_coin_list",
        return_value=[
            {"id": "bitcoin", "name": "Bitcoin", "symbol": "btc"},
        ],
    )
    def test_sync_supported_coins_updates_existing_rows_and_reactivates(
        self, mock_supported
    ):
        Coin.objects.create(
            cg_id="bitcoin",
            name="Old Bitcoin",
            symbol="OLD",
            is_active=False,
        )

        result = sync_supported_coins()

        mock_supported.assert_called_once_with()
        self.assertEqual(
            result,
            SupportedCoinSyncResult(
                created=0, updated=1, deactivated=0, skipped=0, failed=0
            ),
        )
        self.assertEqual(Coin.objects.count(), 1)

        bitcoin = Coin.objects.get(cg_id="bitcoin")
        self.assertEqual(bitcoin.name, "Bitcoin")
        self.assertEqual(bitcoin.symbol, "btc")
        self.assertTrue(bitcoin.is_active)

    @patch(
        "coins.sync.get_supported_coin_list",
        return_value=[
            {"id": "bitcoin", "name": "Bitcoin", "symbol": "btc"},
        ],
    )
    def test_sync_supported_coins_reactivates_unchanged_returned_rows(
        self, mock_supported
    ):
        coin = Coin.objects.create(
            cg_id="bitcoin",
            name="Bitcoin",
            symbol="btc",
            is_active=False,
        )

        result = sync_supported_coins()

        mock_supported.assert_called_once_with()
        self.assertEqual(
            result,
            SupportedCoinSyncResult(
                created=0, updated=1, deactivated=0, skipped=0, failed=0
            ),
        )
        coin.refresh_from_db()
        self.assertEqual(Coin.objects.count(), 1)
        self.assertEqual(coin.name, "Bitcoin")
        self.assertEqual(coin.symbol, "btc")
        self.assertTrue(coin.is_active)

    @patch(
        "coins.sync.get_supported_coin_list",
        return_value=[
            {"id": "bitcoin", "name": "Bitcoin", "symbol": "btc"},
        ],
    )
    def test_sync_supported_coins_deactivates_missing_rows(self, mock_supported):
        bitcoin = Coin.objects.create(
            cg_id="bitcoin",
            name="Bitcoin",
            symbol="btc",
            is_active=True,
        )
        litecoin = Coin.objects.create(
            cg_id="litecoin",
            name="Litecoin",
            symbol="ltc",
            is_active=True,
        )

        result = sync_supported_coins()

        mock_supported.assert_called_once_with()
        self.assertEqual(
            result,
            SupportedCoinSyncResult(
                created=0, updated=0, deactivated=1, skipped=1, failed=0
            ),
        )
        bitcoin.refresh_from_db()
        litecoin.refresh_from_db()
        self.assertTrue(bitcoin.is_active)
        self.assertFalse(litecoin.is_active)

    @patch(
        "coins.sync.get_supported_coin_list",
        return_value=[
            {"id": "bitcoin", "name": "Bitcoin", "symbol": "btc"},
            {"name": "Missing ID", "symbol": "mid"},
            {"id": "blank-name", "name": "", "symbol": "blk"},
            {"id": "blank-symbol", "name": "Blank Symbol", "symbol": " "},
            None,
        ],
    )
    def test_sync_supported_coins_counts_malformed_rows_as_failed(self, mock_supported):
        result = sync_supported_coins()

        mock_supported.assert_called_once_with()
        self.assertEqual(
            result,
            SupportedCoinSyncResult(
                created=1, updated=0, deactivated=0, skipped=0, failed=4
            ),
        )
        self.assertEqual(Coin.objects.count(), 1)
        self.assertTrue(Coin.objects.filter(cg_id="bitcoin").exists())


class SyncSupportedCoinsCommandTest(TestCase):
    @patch("coins.management.commands.sync_supported_coins.sync_supported_coins")
    def test_command_runs_sync_once(self, mock_sync):
        mock_sync.return_value = SupportedCoinSyncResult(
            created=1, updated=2, deactivated=3, skipped=4, failed=5
        )

        with self.assertLogs(
            "coins.management.commands.sync_supported_coins", level="INFO"
        ) as logs:
            call_command("sync_supported_coins")

        mock_sync.assert_called_once_with()
        self.assertIn(
            "created=1 updated=2 deactivated=3 skipped=4 failed=5",
            logs.output[0],
        )
        self.assertIn("skipped malformed rows: failed=5", logs.output[1])

    @patch(
        "coins.management.commands.sync_supported_coins.sync_supported_coins",
        side_effect=CoinGeckoUnavailableError("down"),
    )
    def test_command_failure_skips_without_crashing(self, mock_sync):
        Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        before = Coin.objects.count()

        with self.assertLogs(
            "coins.management.commands.sync_supported_coins", level="WARNING"
        ) as logs:
            call_command("sync_supported_coins")

        mock_sync.assert_called_once_with()
        self.assertEqual(Coin.objects.count(), before)
        self.assertIn("type=CoinGeckoUnavailableError", logs.output[0])


class RunapschedulerCommandTest(SimpleTestCase):
    def test_runapscheduler_does_not_expose_run_now(self):
        parser = RunapschedulerCommand().create_parser("manage.py", "runapscheduler")
        option_dests = {action.dest for action in parser._actions}

        self.assertNotIn("run_now", option_dests)

    @patch("coins.management.commands.runapscheduler.DjangoJobStore")
    @patch("coins.management.commands.runapscheduler.BlockingScheduler")
    def test_sync_interval_uses_documented_seconds_cadence(
        self, mock_scheduler_class, mock_job_store
    ):
        scheduler = mock_scheduler_class.return_value

        RunapschedulerCommand().handle()

        sync_job = scheduler.add_job.call_args_list[0]
        self.assertEqual(sync_job.args[:2], (sync_supported_coins_job, "interval"))
        self.assertEqual(
            sync_job.kwargs["seconds"], SUPPORTED_COINS_SYNC_INTERVAL_SECONDS
        )
        self.assertEqual(sync_job.kwargs["seconds"], 2 * 60 * 60 + 5 * 60)
        self.assertNotIn("minutes", sync_job.kwargs)
        mock_job_store.assert_called_once_with()
        scheduler.start.assert_called_once_with()


# ``sync_supported_coins_job`` is wrapped in ``@util.close_old_connections``,
# which closes the DB connection on exit — that would corrupt a ``TestCase``'s
# wrapping transaction, so this lives in a ``TransactionTestCase``.
class SchedulerFallbackTest(TransactionTestCase):
    @patch(
        "coins.management.commands.runapscheduler.sync_supported_coins",
        return_value=SupportedCoinSyncResult(
            created=1, updated=2, deactivated=3, skipped=4, failed=5
        ),
    )
    def test_scheduler_success_logs_sync_counts(self, mock_sync):
        with self.assertLogs(
            "coins.management.commands.runapscheduler", level="INFO"
        ) as logs:
            sync_supported_coins_job()

        self.assertTrue(mock_sync.called)
        self.assertIn(
            "created=1 updated=2 deactivated=3 skipped=4 failed=5",
            logs.output[0],
        )

    @patch(
        "coins.management.commands.runapscheduler.sync_supported_coins",
        side_effect=CoinGeckoUnavailableError("down"),
    )
    def test_scheduler_failure_skips_without_crashing(self, mock_sync):
        Coin.objects.create(cg_id="bitcoin", name="Bitcoin", symbol="BTC")
        before = Coin.objects.count()
        # Must not raise: the blocking scheduler stays alive.
        with self.assertLogs(
            "coins.management.commands.runapscheduler", level="WARNING"
        ) as logs:
            sync_supported_coins_job()
        self.assertTrue(mock_sync.called)
        self.assertEqual(Coin.objects.count(), before)
        self.assertIn("type=CoinGeckoUnavailableError", logs.output[0])
