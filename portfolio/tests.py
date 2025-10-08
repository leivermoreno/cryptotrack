from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from coins.models import Coin
from .models import PortfolioTransaction


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

    def test_portfolio_overview_authenticated(self):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(reverse("portfolio:overview"))
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
        self.assertRedirects(response, reverse("login", query={"next": url}))

    def test_portfolio_overview_no_transactions(self):
        User.objects.create_user(username="testuser2", password="pass")
        self.client.login(username="testuser2", password="pass")
        response = self.client.get(reverse("portfolio:overview"))
        self.assertContains(response, "No coins in your portfolio yet.")
        self.assertEqual(len(response.context["coin_list"]), 0)

    def test_portfolio_overview_sorting(self):
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
