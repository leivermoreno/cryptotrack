# Accounts App Inspection

## Scope

Inspected `accounts/` plus shared wiring needed to understand authentication flow:

- `accounts/models.py`
- `accounts/views.py`
- `accounts/urls.py`
- `accounts/templates/registration/login.html`
- `accounts/templates/registration/register.html`
- `accounts/admin.py`
- `accounts/tests.py`
- `accounts/apps.py`
- `accounts/migrations/`
- `crypto_track/settings.py`
- `crypto_track/urls.py`
- `templates/base.html`
- `requirements.txt`
- `README.md`
- Narrow integration touchpoints in `coins/` and `portfolio/` where authenticated users own data or views require login.

No application code was changed.

## What The App Does

`accounts` provides the project authentication entry points:

- Login at `/accounts/login/`, using Django's built-in `LoginView` and `accounts/templates/registration/login.html`.
- Registration at `/accounts/register/`, using a custom function view around Django's built-in `UserCreationForm`.
- Logout at `/accounts/logout/`, using Django's built-in `LogoutView`.

The app does not define its own user model, profile model, forms, services, admin classes, signals, or account-specific business data. It is a thin wrapper around Django auth with custom templates and route names.

README describes user authentication as a first-class feature of the product (`README.md:7-15`), but the implementation is currently minimal.

## Architecture

The app has a small, conventional Django shape:

- App config: `accounts/apps.py:4-6` declares `AccountsConfig`.
- Models: `accounts/models.py:1-3` is empty aside from the default import/comment.
- Admin: `accounts/admin.py:1-3` has no custom registrations.
- URLs: `accounts/urls.py:5-9` maps auth-related routes.
- Views: `accounts/views.py:4-15` contains only the registration view.
- Templates: `accounts/templates/registration/login.html` and `accounts/templates/registration/register.html` render crispy forms inside `base.html`.
- Tests: `accounts/tests.py:1-3` is empty.

The app depends on:

- `django.contrib.auth` and `django.contrib.sessions`, enabled in `INSTALLED_APPS` and middleware (`crypto_track/settings.py:40-68`).
- Django template context processors for `request`, `auth`, and `messages` (`crypto_track/settings.py:72-83`).
- `django-crispy-forms` and `crispy-bootstrap5` for form rendering (`crypto_track/settings.py:51-58`, `requirements.txt:7-11`).
- Bootstrap 5 loaded from jsDelivr in the base template (`templates/base.html:10-15`).

## URL And View Workflow

Project-level routing includes `accounts.urls` under `/accounts/` (`crypto_track/urls.py:21-25`).

`accounts/urls.py` defines global URL names, not an `accounts` namespace:

- `login`: `/accounts/login/` (`accounts/urls.py:6`)
- `register`: `/accounts/register/` (`accounts/urls.py:7`)
- `logout`: `/accounts/logout/` (`accounts/urls.py:8`)

The global names are used directly by the base navbar and auth templates:

- Login link: `templates/base.html:38-40`
- Register link: `templates/base.html:41-43`
- Logout form action: `templates/base.html:33-36`
- Register link from login page: `accounts/templates/registration/login.html:21`
- Login link from register page: `accounts/templates/registration/register.html:15`

### Login

Login is handled by:

```python
path('login/', auth_views.LoginView.as_view(redirect_authenticated_user=True, next_page='/'), name='login')
```

Key behavior:

- Uses Django's default `registration/login.html` template lookup, satisfied by `accounts/templates/registration/login.html`.
- Authenticated users are redirected away from the login page because `redirect_authenticated_user=True`.
- Default success target is `/` via `next_page='/'`, unless a valid `next` parameter is supplied.
- The template posts back to the same URL with CSRF protection and includes hidden `next` propagation (`accounts/templates/registration/login.html:12-20`).
- If `next` exists, the template shows "Please log in to see this page." (`accounts/templates/registration/login.html:8-10`).

### Registration

Registration is implemented in `accounts/views.py:4-15`:

- Authenticated users are redirected to `coins:index` (`accounts/views.py:5-6`).
- Anonymous GET requests instantiate `UserCreationForm` (`accounts/views.py:13-14`).
- POST requests validate `UserCreationForm(request.POST)` (`accounts/views.py:8-10`).
- Valid registrations call `form.save()` and redirect to `login` (`accounts/views.py:10-12`).
- Invalid forms fall through and re-render `registration/register.html` with validation errors.

Registration does not automatically log in the newly created user. It also does not collect email, names, profile details, marketing preferences, consent, or account verification state.

### Logout

Logout is handled by:

```python
path('logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout')
```

The navbar triggers logout through a POST form with CSRF token (`templates/base.html:33-36`). This matches modern Django logout expectations and avoids exposing logout as a simple link.

After logout, users are redirected to `/`.

## Template And UI Behavior

Both account templates extend the global base template:

- Login extends `base.html` and loads crispy form filters (`accounts/templates/registration/login.html:1-2`).
- Register extends `base.html` and loads crispy form filters (`accounts/templates/registration/register.html:1-2`).

The forms are centered with Bootstrap utility classes:

- Login container and heading: `accounts/templates/registration/login.html:4-7`
- Register container and heading: `accounts/templates/registration/register.html:4-7`

Both templates render forms through `{{ form|crispy }}`:

- Login: `accounts/templates/registration/login.html:12-20`
- Register: `accounts/templates/registration/register.html:8-14`

The base template controls navigation based on `request.user.is_authenticated` (`templates/base.html:26-44`):

- Authenticated users see Watchlist, Portfolio, and Logout.
- Anonymous users see Login and Register.
- The search form is always included (`templates/base.html:47`).

Potential polish issues:

- The `title` block is nested inside the page heading in both account templates (`accounts/templates/registration/login.html:6`, `accounts/templates/registration/register.html:6`). It works as a compact pattern, but it couples browser title text to visible heading text.
- The templates are functional but bare: no explanatory errors beyond crispy output, no message on successful registration, and no account-specific layout refinements.
- The account forms are centered vertically via `flex-grow-1`, but `body`/parent layout constraints are not visible in `base.html`; this may not consistently create true vertical centering.

## Model, Admin, And Migration State

`accounts` has no models:

- `accounts/models.py:1-3` contains only the generated placeholder.
- `accounts/migrations/__init__.py` exists, but there are no migration files.
- `accounts/admin.py:1-3` has no custom admin registrations.

User persistence is entirely Django's built-in auth user model. The app currently uses the default `auth.User`; there is no `AUTH_USER_MODEL` override in `crypto_track/settings.py`.

Important integration detail: other apps import `django.contrib.auth.models.User` directly:

- `coins/models.py:1-2`
- `portfolio/models.py:3-6`

Those apps store user-owned data:

- `coins.Watchlist.user` is a `ForeignKey(User, on_delete=models.CASCADE)` (`coins/models.py:15-18`).
- `portfolio.PortfolioTransaction.user` is a `ForeignKey(User, on_delete=models.CASCADE)` (`portfolio/models.py:9-15`).

Deletion of a user cascades to watchlist and portfolio transactions. That behavior is likely acceptable for a simple app, but it should be made explicit before adding profile/account deletion features.

## Authentication Integration With Other Apps

`coins` and `portfolio` depend on account login state:

- The public coin index includes a user's watchlist if authenticated (`coins/views.py:23-47`).
- Watchlist toggle is login-protected and POST-only (`coins/views.py:79-93`).
- Watchlist page is login-protected (`coins/views.py:96-117`).
- Portfolio overview, transaction list, create/edit transaction, and delete transaction are login-protected (`portfolio/views.py:25-160`).

Because the project does not set `LOGIN_URL`, Django's default `/accounts/login/` is relied on implicitly. This happens to match the current route. Tests in other apps also assume the global `login` URL name:

- Coins unauthenticated watchlist actions assert redirects to `reverse("login", query={"next": url})` (`coins/tests.py:79-99`).
- Portfolio unauthenticated overview asserts the same contract (`portfolio/tests.py:78-82`).

This coupling is lightweight but fragile during refactors. If account URLs are namespaced or moved, update `LOGIN_URL`, tests, templates, and `login_required` redirect expectations together.

## Settings And Dependency Integration

Relevant settings:

- `accounts.apps.AccountsConfig` is installed (`crypto_track/settings.py:47-54`).
- Auth, session, CSRF, and messages middleware are present (`crypto_track/settings.py:60-68`).
- Template context processors include `request`, `auth`, and `messages` (`crypto_track/settings.py:72-83`).
- Password validators are enabled (`crypto_track/settings.py:115-128`).
- Crispy Bootstrap 5 is configured (`crypto_track/settings.py:51-58`).

Settings gaps that affect account hardening:

- No explicit `LOGIN_URL`, `LOGIN_REDIRECT_URL`, or `LOGOUT_REDIRECT_URL`; behavior is split between Django defaults and per-view `next_page` arguments.
- No explicit production cookie/security settings such as `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`, or `SESSION_COOKIE_HTTPONLY` review.
- `ALLOWED_HOSTS = ["*"]` (`crypto_track/settings.py:34`) is broad for production.
- A development fallback `SECRET_KEY` exists (`crypto_track/settings.py:25-29`).
- `DEBUG` is controlled by `PYTHON_ENV != "production"` (`crypto_track/settings.py:31-35`), so environment naming mistakes could expose debug behavior.

Those are project-wide concerns, but they directly affect authentication safety.

## Test Coverage

`accounts/tests.py` is empty (`accounts/tests.py:1-3`). There are no direct tests for:

- Login page rendering.
- Login success/failure.
- Authenticated-user redirect from login.
- Registration GET.
- Registration success.
- Registration validation errors.
- Authenticated-user redirect from registration.
- Logout POST behavior.
- Navbar auth/anonymous states.
- Template availability for Django auth views.

Indirect coverage exists in other apps:

- Coins tests verify unauthenticated redirects to the global `login` URL with `next` (`coins/tests.py:79-99`).
- Portfolio tests verify unauthenticated redirect to `login` with `next` (`portfolio/tests.py:78-82`).
- Coins and portfolio tests create default Django users and authenticate through the test client (`coins/tests.py:31-99`, `portfolio/tests.py:51-104`).

This gives some confidence that the `login` URL name exists and `login_required` works, but it does not validate the account pages themselves.

## Risks, Bugs, And Technical Debt

1. **No direct account tests.** The app's core feature has no local tests, so template regressions, route changes, and registration behavior changes would be easy to miss.

2. **Direct dependency on `auth.User`.** `coins` and `portfolio` import `django.contrib.auth.models.User` directly (`coins/models.py:2`, `portfolio/models.py:5`). This makes a future custom user model harder. A refactor should move model fields to `settings.AUTH_USER_MODEL` and runtime references to `get_user_model()` where appropriate.

3. **Implicit login URL contract.** The project relies on Django's default `LOGIN_URL` matching `/accounts/login/`. That is currently true, but brittle if URLs are renamed, namespaced, or reorganized.

4. **Global account URL names.** `accounts/urls.py` does not define `app_name`, so `login`, `register`, and `logout` live in the global URL namespace. This matches Django auth conventions but increases collision risk as the app grows.

5. **Minimal registration workflow.** Registration only creates username/password users. There is no email collection, confirmation, success message, automatic login, anti-abuse control, invitation flow, or profile initialization.

6. **No account lifecycle model.** There is no place for user preferences, profile data, account status, onboarding state, or deletion/audit metadata.

7. **Project security defaults need hardening.** Current settings include broad allowed hosts, fallback secret key, and no explicit secure cookie/HTTPS settings. These are project-level issues with direct auth impact.

8. **UX is serviceable but under-polished.** Login/register screens are basic crispy forms. They do not provide a polished account journey, contextual success/error messaging, or a clear post-registration next step.

9. **Cascade delete behavior is implicit.** Deleting a user deletes watchlist and portfolio transactions through `on_delete=models.CASCADE`. This should be intentionally documented or adjusted before adding account deletion/admin tooling.

10. **No account admin surface.** The app does not customize admin behavior for account support workflows. It relies entirely on Django's built-in User admin from `django.contrib.auth`.

## Refactor And Polish Opportunities

### Near-Term Cleanup

- Add focused `accounts` tests for login, logout, registration, redirect behavior, and templates.
- Set explicit `LOGIN_URL`, `LOGIN_REDIRECT_URL`, and `LOGOUT_REDIRECT_URL` in settings to make auth behavior intentional.
- Decide whether to keep global URL names for Django compatibility or introduce `accounts` namespacing with compatibility aliases.
- Add a registration success message before redirecting to login.
- Preserve an intended destination through registration when a user starts from a protected page.
- Normalize quote/style formatting in `accounts/urls.py` and templates to match the rest of the project.

### User Model And Data Ownership

- Decide early whether the refactor needs a custom user model. If yes, do it before more account data is added.
- Replace direct `User` imports in app models with `settings.AUTH_USER_MODEL`.
- Use `get_user_model()` in tests/factories/runtime code where a concrete user class is needed.
- Document expected behavior for user deletion and whether portfolio/watchlist history should be hard-deleted, anonymized, or retained.

### Account Experience

- Consider a custom registration form if email, display name, validation, or profile creation is needed.
- Consider automatic login after registration if the product goal is fast onboarding.
- Add clear success/error messaging for registration and logout.
- Improve login/register templates as a cohesive account flow while keeping Bootstrap/crispy consistency.
- Add password reset/change views if this app is expected to be usable beyond a demo environment.

### Security Hardening

- Add production-safe auth/session settings, including secure cookies and HTTPS redirect policy.
- Replace `ALLOWED_HOSTS = ["*"]` with environment-specific hosts for production.
- Require a production secret key rather than allowing fallback defaults outside development.
- Review CSRF trusted origin handling and failure mode for production.
- Consider rate limiting or bot protection on login and registration if publicly deployed.

### Testing Strategy

- Add unit tests for `register`.
- Add integration tests for auth URLs and templates.
- Add navbar rendering tests for authenticated vs anonymous users.
- Add regression tests around `next` parameter behavior for login and protected views.
- Add tests proving user-owned watchlist/portfolio data stays isolated between users.

## Refactor Kickoff Summary

`accounts` is currently a thin Django-auth adapter: useful, simple, and easy to reason about, but under-tested and not yet designed for a polished product account lifecycle. The most important refactor decisions are whether to introduce a custom user model, how explicit to make auth URL/settings contracts, and what user onboarding/recovery/security behavior the finished app needs. Before broad polishing, add direct account tests and settle the user model strategy because those choices affect `coins`, `portfolio`, migrations, and future account data.
