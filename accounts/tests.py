import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core import mail
from django.test import Client, TestCase, override_settings
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

    def test_login_register_link_preserves_safe_next_param(self):
        """The login page carries forward a safe protected-page destination."""
        next_url = reverse("coins:watchlist")
        response = self.client.get(reverse("accounts:login", query={"next": next_url}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'name="next" value="{next_url}"')
        self.assertContains(response, "Log in to continue to the requested page.")
        self.assertContains(
            response,
            f'href="{reverse("accounts:register", query={"next": next_url})}"',
        )

    def test_login_register_link_drops_unsafe_next_param(self):
        """The register link does not preserve external redirect targets."""
        response = self.client.get(
            reverse("accounts:login", query={"next": "https://evil.example/"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("accounts:register")}"')
        self.assertNotContains(response, f"{reverse('accounts:register')}?next=")

    def test_login_links_to_password_reset(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("accounts:password_reset")}"')

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

    def test_register_get_preserves_safe_next_param(self):
        """GET register stores a safe destination in the form and login link."""
        next_url = reverse("coins:watchlist")
        response = self.client.get(
            reverse("accounts:register", query={"next": next_url})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'name="next" value="{next_url}"')
        self.assertContains(
            response,
            f'href="{reverse("accounts:login", query={"next": next_url})}"',
        )

    def test_register_post_valid_creates_user_and_redirects_to_login(self):
        """Valid POST creates the user, redirects to login, and does NOT auto-log-in.

        This is the chosen registration flow: the app shows a success message,
        preserves any safe next destination for the login step, and does not
        authenticate the new user until they submit the login form.
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
        # No auto-login: the first authenticated session starts at the login form.
        self.assertNotIn("_auth_user_id", self.client.session)
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertIn("Your account has been created. You can now log in.", messages)

    def test_register_success_message_renders_on_login_page(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newuser",
                "password1": STRONG_PASSWORD,
                "password2": STRONG_PASSWORD,
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertContains(
            response, "Your account has been created. You can now log in."
        )
        self.assertContains(response, "alert-success")

    def test_register_post_valid_preserves_safe_next_param_to_login(self):
        """After registration, login receives the safe intended destination."""
        next_url = reverse("coins:watchlist")
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newuser",
                "password1": STRONG_PASSWORD,
                "password2": STRONG_PASSWORD,
                "next": next_url,
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:login", query={"next": next_url}),
            fetch_redirect_response=False,
        )
        self.assertTrue(User.objects.filter(username="newuser").exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_register_post_valid_drops_unsafe_next_param(self):
        """Unsafe destinations are not forwarded to login after registration."""
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newuser",
                "password1": STRONG_PASSWORD,
                "password2": STRONG_PASSWORD,
                "next": "//evil.example/",
            },
        )

        self.assertRedirects(
            response, reverse("accounts:login"), fetch_redirect_response=False
        )
        self.assertTrue(User.objects.filter(username="newuser").exists())
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

    def test_register_post_invalid_preserves_safe_next_param(self):
        """Invalid registration keeps the safe next value for correction."""
        next_url = reverse("coins:watchlist")
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newuser",
                "password1": STRONG_PASSWORD,
                "password2": "different-" + STRONG_PASSWORD,
                "next": next_url,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/register.html")
        self.assertContains(response, f'name="next" value="{next_url}"')
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_register_get_drops_unsafe_next_param(self):
        """Unsafe destinations are not rendered into the registration page."""
        response = self.client.get(
            reverse("accounts:register", query={"next": "https://evil.example/"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="next"')
        self.assertNotContains(response, "https://evil.example/")

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


class PasswordChangeViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="erin", password=STRONG_PASSWORD)

    def test_password_change_requires_login(self):
        response = self.client.get(reverse("accounts:password_change"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:password_change')}",
            fetch_redirect_response=False,
        )

    def test_password_change_get_renders_template_for_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:password_change"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/password_change_form.html")

    def test_password_change_done_renders_for_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:password_change_done"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/password_change_done.html")

    def test_password_change_post_updates_password_and_keeps_session(self):
        self.client.force_login(self.user)
        new_password = "N3wStr0ngPass!word42"

        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": STRONG_PASSWORD,
                "new_password1": new_password,
                "new_password2": new_password,
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:password_change_done"),
            fetch_redirect_response=False,
        )
        self.assertIn("_auth_user_id", self.client.session)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        self.assertFalse(self.client.login(username="erin", password=STRONG_PASSWORD))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="frank",
            email="frank@example.com",
            password=STRONG_PASSWORD,
        )

    def test_password_reset_routes_render_templates(self):
        routes = [
            ("accounts:password_reset", "accounts/password_reset_form.html"),
            ("accounts:password_reset_done", "accounts/password_reset_done.html"),
            (
                "accounts:password_reset_complete",
                "accounts/password_reset_complete.html",
            ),
        ]

        for route_name, template_name in routes:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)

    def test_password_reset_email_token_flow(self):
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": self.user.email}
        )

        self.assertRedirects(
            response,
            reverse("accounts:password_reset_done"),
            fetch_redirect_response=False,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "CryptoTrack password reset")

        match = re.search(
            r"http://testserver(?P<path>/accounts/password-reset/[^/]+/[^/]+/)",
            mail.outbox[0].body,
        )
        self.assertIsNotNone(match)

        response = self.client.get(match.group("path"))
        self.assertEqual(response.status_code, 302)

        set_password_url = response["Location"]
        response = self.client.get(set_password_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/password_reset_confirm.html")
        self.assertTrue(response.context["validlink"])

        new_password = "R3setStr0ngPass!word42"
        response = self.client.post(
            set_password_url,
            {"new_password1": new_password, "new_password2": new_password},
        )

        self.assertRedirects(
            response,
            reverse("accounts:password_reset_complete"),
            fetch_redirect_response=False,
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        self.assertTrue(self.client.login(username="frank", password=new_password))


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
        self.assertContains(response, reverse("accounts:password_change"))
        self.assertContains(response, reverse("coins:watchlist"))
        self.assertContains(response, reverse("portfolio:overview"))


class AccountUrlCompatibilityTest(TestCase):
    def test_global_auth_url_aliases_still_resolve(self):
        self.assertEqual(reverse("login"), reverse("accounts:login"))
        self.assertEqual(reverse("logout"), reverse("accounts:logout"))
        self.assertEqual(reverse("register"), reverse("accounts:register"))
        self.assertEqual(reverse("password_reset"), reverse("accounts:password_reset"))
        self.assertEqual(
            reverse("password_reset_done"), reverse("accounts:password_reset_done")
        )
        self.assertEqual(
            reverse(
                "password_reset_confirm",
                kwargs={"uidb64": "uid", "token": "token"},
            ),
            reverse(
                "accounts:password_reset_confirm",
                kwargs={"uidb64": "uid", "token": "token"},
            ),
        )
        self.assertEqual(
            reverse("password_reset_complete"),
            reverse("accounts:password_reset_complete"),
        )
        self.assertEqual(
            reverse("password_change"), reverse("accounts:password_change")
        )
        self.assertEqual(
            reverse("password_change_done"),
            reverse("accounts:password_change_done"),
        )
