import unittest
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from common.test_utils import make_market_coin, market_response

from .models import Coin, Watchlist


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
            response, expected_url=reverse("login", query={"next": url})
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
            response, expected_url=reverse("login", query={"next": url})
        )


# ---------------------------------------------------------------------------
# Subtask 2.4 additions: watchlist toggling, invalid ids, inactive coins,
# query preservation, and unsafe ``next`` values.
# Section 2 safety-net baseline: GREEN characterizations of current behavior,
# plus ``@unittest.expectedFailure`` for known bugs (asserting the desired
# correct behavior) so the suite stays green now and flips to XPASS once fixed.
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
    """Search preserves the term across pagination (GREEN); the index page's
    custom prev/next pagination dropping sort/direction is a known bug
    (expectedFailure)."""

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
            response, "page=2&sort=price&direction=desc&search=Preserve"
        )

    @unittest.expectedFailure
    @patch("coins.views.get_page_count", return_value=3)
    @patch(
        "coins.views.get_coin_list_with_market",
        return_value=market_response("bitcoin"),
    )
    def test_index_pagination_preserves_sort_direction(
        self, mock_market, mock_page_count
    ):
        # KNOWN BUG: inspection/coins.md "Index Flow" / Key Risks (index
        # template pagination drops sort & direction). Fix in step 7.7.
        # Desired: the custom prev/next links preserve sort=price&direction=desc.
        # Currently coins/index.html renders only ``?page=N``, so this fails now
        # and will XPASS after step 7.7.
        response = self.client.get(
            reverse("coins:index") + "?sort=price&direction=desc&page=1"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "page=2&sort=price&direction=desc")


class OpenRedirectTest(TestCase):
    """The ``next`` open-redirect (inspection/coins.md Key Risks #7). A valid
    local ``next`` is honored (GREEN); unsafe off-site values must be rejected
    (expectedFailure until step 4.2 adds safe-redirect validation)."""

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

    @unittest.expectedFailure
    def test_unsafe_next_is_rejected(self):
        # KNOWN BUG: inspection/coins.md Key Risks #7 (open redirect). Fix in
        # step 4.2. add_remove_to_watchlist redirects to POST['next'] directly,
        # so a crafted off-site value redirects the user off-site. Desired: an
        # unsafe destination is rejected in favor of a safe local path.
        # Currently the view honors the external URL, so this fails now and will
        # XPASS after step 4.2 adds url_has_allowed_host_and_scheme validation.
        self.client.login(username="testuser", password="pass")
        url = reverse("coins:add_remove_to_watchlist", args=[self.coin.cg_id])
        for unsafe in ["https://evil.example/", "//evil.example/", "\\evil.example"]:
            with self.subTest(next=unsafe):
                response = self.client.post(url, {"next": unsafe})
                self.assertTrue(
                    url_has_allowed_host_and_scheme(
                        response.url, allowed_hosts={"testserver"}
                    ),
                    msg=f"redirected to unsafe destination {response.url!r}",
                )
