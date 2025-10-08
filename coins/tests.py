from django.db import IntegrityError
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
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

    def test_render_index_view(self):
        response = self.client.get(reverse("coins:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "coins/index.html")
        self.assertIn("coin_list", response.context)

    def test_render_search_view(self):
        response = self.client.get(reverse("coins:search") + "?search=Bitcoin")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "coins/search.html")
        self.assertIn("coin_list", response.context)

    def test_render_search_empty_query_redirects(self):
        response = self.client.get(reverse("coins:search"))
        self.assertRedirects(response, expected_url=reverse("coins:index"))

    def test_add_remove_to_watchlist_authenticated(self):
        # add
        self.client.login(username="testuser", password="pass")
        data = {"next": reverse("coins:watchlist")}
        url = reverse("coins:add_remove_to_watchlist", args=[self.coin.cg_id])
        response = self.client.post(url, data)
        self.assertRedirects(response, expected_url=reverse("coins:watchlist"))
        self.assertTrue(
            Watchlist.objects.filter(user=self.user, coin=self.coin).exists()
        )
        # remove
        response = self.client.post(url, data)
        self.assertRedirects(response, expected_url=reverse("coins:watchlist"))
        self.assertFalse(
            Watchlist.objects.filter(user=self.user, coin=self.coin).exists()
        )

    def test_add_remove_to_watchlist_invalid_coin(self):
        self.client.login(username="testuser", password="pass")
        url = reverse("coins:add_remove_to_watchlist", args=["invalidcgid"])
        response = self.client.post(url, {"next": reverse("coins:watchlist")})
        self.assertRedirects(response, expected_url=reverse("coins:watchlist"))

    def test_add_remove_to_watchlist_unauthenticated(self):
        url = reverse("coins:add_remove_to_watchlist", args=[self.coin.cg_id])
        response = self.client.post(url)
        self.assertRedirects(
            response, expected_url=reverse("login", query={"next": url})
        )

    def test_render_watchlist_authenticated(self):
        Watchlist.objects.create(user=self.user, coin=self.coin)
        self.client.login(username="testuser", password="pass")
        response = self.client.get(reverse("coins:watchlist"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "coins/watchlist.html")
        self.assertIn("coin_list", response.context)

    def test_render_watchlist_unauthenticated(self):
        url = reverse("coins:watchlist")
        response = self.client.get(url)
        self.assertRedirects(
            response, expected_url=reverse("login", query={"next": url})
        )
