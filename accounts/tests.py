from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()

# A password strong enough to pass Django's default AUTH_PASSWORD_VALIDATORS
# (min length, not all-numeric, not a common password, not similar to username).
STRONG_PASSWORD = "Str0ngPass!word42"


class LoginViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="alice", password=STRONG_PASSWORD)

    def test_login_get_renders_template(self):
        """GET login returns 200 and uses registration/login.html."""
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")

    def test_login_post_valid_authenticates_and_redirects(self):
        """Valid credentials log the user in and redirect to LOGIN_REDIRECT_URL."""
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "alice", "password": STRONG_PASSWORD},
        )
        self.assertRedirects(
            response,
            settings.LOGIN_REDIRECT_URL,
            fetch_redirect_response=False,
        )
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_login_post_invalid_rerenders_with_error(self):
        """Bad credentials re-render (200), user stays anonymous, form has errors."""
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "alice", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")
        self.assertFalse(response.context["user"].is_authenticated)
        self.assertTrue(response.context["form"].errors)

    def test_login_honors_next_param(self):
        """Logging in from a protected page redirects to the next target."""
        next_url = reverse("coins:watchlist")
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "alice", "password": STRONG_PASSWORD, "next": next_url},
        )
        self.assertRedirects(response, next_url, fetch_redirect_response=False)

    def test_authenticated_user_redirected_away_from_login(self):
        """redirect_authenticated_user=True sends logged-in users off the login page."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:login"))
        self.assertRedirects(
            response,
            settings.LOGIN_REDIRECT_URL,
            fetch_redirect_response=False,
        )


class RegisterViewTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_register_get_renders_template(self):
        """GET register returns 200 and uses registration/register.html."""
        response = self.client.get(reverse("accounts:register"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/register.html")

    def test_register_post_valid_creates_user_and_redirects_to_login(self):
        """Valid POST creates the user, redirects to login, and does NOT auto-log-in.

        Not auto-logging-in is the current behavior (accounts/views.py redirects
        to 'login' after form.save() without authenticating). Auto-login is a
        deferred enhancement (Section 14), not a bug.
        """
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newuser",
                "password1": STRONG_PASSWORD,
                "password2": STRONG_PASSWORD,
            },
        )
        self.assertRedirects(
            response, reverse("accounts:login"), fetch_redirect_response=False
        )
        self.assertTrue(User.objects.filter(username="newuser").exists())
        # Client is not authenticated after registration (current behavior).
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_register_post_invalid_rerenders_and_creates_no_user(self):
        """Mismatched passwords re-render with errors and create no user."""
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newuser",
                "password1": STRONG_PASSWORD,
                "password2": "different-" + STRONG_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/register.html")
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_authenticated_user_redirected_from_register(self):
        """Authenticated users visiting register are redirected to coins:index."""
        user = User.objects.create_user(username="bob", password=STRONG_PASSWORD)
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:register"))
        self.assertRedirects(
            response, reverse("coins:index"), fetch_redirect_response=False
        )


class LogoutViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="carol", password=STRONG_PASSWORD)

    def test_logout_post_logs_out_and_redirects(self):
        """POST logout clears the session and redirects to LOGOUT_REDIRECT_URL."""
        self.client.force_login(self.user)
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(
            response,
            settings.LOGOUT_REDIRECT_URL,
            fetch_redirect_response=False,
        )
        self.assertNotIn("_auth_user_id", self.client.session)


class NavbarAuthStateTest(TestCase):
    """The base-template navbar shows different links for anon vs. authed users.

    The login page renders base.html for anonymous users without hitting
    CoinGecko, so it is a cheap surface for the anonymous case. Authenticated
    users are redirected away from login/register, so the authed navbar is
    verified on the coins index (with CoinGecko mocked).
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="dave", password=STRONG_PASSWORD)

    def test_anonymous_navbar_shows_login_and_register(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("accounts:login"))
        self.assertContains(response, reverse("accounts:register"))

    def test_authenticated_navbar_shows_logout_and_app_links(self):
        """An authed rendered page exposes Logout, Watchlist, and Portfolio links."""
        from unittest.mock import patch

        from common.test_utils import market_response

        self.client.force_login(self.user)
        with (
            patch("coins.views.get_page_count", return_value=1),
            patch(
                "coins.views.get_coin_list_with_market",
                return_value=market_response("bitcoin"),
            ),
        ):
            response = self.client.get(reverse("coins:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("accounts:logout"))
        self.assertContains(response, reverse("coins:watchlist"))
        self.assertContains(response, reverse("portfolio:overview"))


class AccountUrlCompatibilityTest(TestCase):
    def test_global_auth_url_aliases_still_resolve(self):
        self.assertEqual(reverse("login"), reverse("accounts:login"))
        self.assertEqual(reverse("logout"), reverse("accounts:logout"))
        self.assertEqual(reverse("register"), reverse("accounts:register"))
