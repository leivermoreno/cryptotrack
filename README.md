# CryptoTrack Portfolio App

CryptoTrack is a Django-based application that enables users to track cryptocurrency prices, manage a personalized
watchlist, and monitor unrealized profit/loss for their portfolio by recording buy and sell operations. The app is
powered by the CoinGecko API.

## Features

- User authentication (registration, login, logout)
- View a list of cryptocurrencies with current prices
- Search for cryptocurrencies by name or symbol
- Add or remove cryptocurrencies from a watchlist
- Record buy and sell operations to track your portfolio
- View useful metrics such as unrealized profit/loss
- Admin panel to manage users, coins, and operations
- Disable coins from appearing in the app (useful for delisted coins)
- Caching to reduce requests to the CoinGecko API
- Background job to keep the database updated with the latest coins from CoinGecko

## Tech Stack

- Django
- PostgreSQL
- Bootstrap 5
- CoinGecko API
- APScheduler for background jobs

## Installation

1. Create a virtual environment, activate it, and install dependencies:

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   pip install -r requirements-dev.txt
   ```

   `requirements-dev.txt` installs the runtime dependencies (via `-r requirements.txt`)
   plus the development tooling (Ruff, pre-commit). A production/PaaS deploy installs
   **only** `requirements.txt` and must never install the dev file.

2. Create postgresql role and database:

   - Create crypto_track role

   - Create crypto_track database owned by crypto_track role

   - Grant connect privilege on postgres database to crypto_track role in order to execute tests

3. Apply migrations:

   ```bash
   python manage.py migrate
   ```

4. Initialize the cache database:

   ```bash
   python manage.py createcachetable
   ```

5. To access the admin panel, create a superuser:

   ```bash
   python manage.py createsuperuser
   ```

6. Set environment variables:

   - `DJANGO_DEBUG`: boolean development toggle (e.g. `true`/`false`). Unset or false runs the app in the production posture (`DEBUG` off), which makes `SECRET_KEY`, `ALLOWED_HOSTS`, and `CSRF_TRUSTED_ORIGINS` required. Set `true` for local development, tests, and CI. Fail-closed: a value that is not a recognized boolean raises a configuration error rather than silently enabling debug.
   - `SECRET_KEY`: Django secret key. Required in production; optional in development, where an insecure built-in fallback is used if unset.
   - `CSRF_TRUSTED_ORIGINS`: comma-separated list of trusted origins, each including a scheme (e.g., `https://example.com`). Required in production; defaults to `http://localhost:8000,http://127.0.0.1:8000` in development.
   - `ALLOWED_HOSTS`: comma-separated hostnames the app serves (e.g., `example.com,www.example.com`). Required in production; defaults to `localhost,127.0.0.1` in development.
   - `COINGECKO_KEY`: API key for CoinGecko
   - `DATABASE_URI` (optional): Database URL (e.g., `postgres://user:password@host:5432/dbname`). Defaults to `postgres://crypto_track@/crypto_track`.

   The project supports `.env` files. You can create a `.env` file in the root directory and add the variables.

   **Production security (optional).** These take effect only when `DEBUG` is off (`DJANGO_DEBUG` unset or false) and all have safe defaults, so they can be left unset. The app is designed for a Railway/PaaS deployment where TLS terminates at the platform edge.

   - `TRUST_PROXY_SSL_HEADER` (default `false`): trust `X-Forwarded-Proto` to determine the original request scheme (sets Django's `SECURE_PROXY_SSL_HEADER`). **On Railway (or any TLS-terminating proxy) set this to `true`.** Because TLS is terminated at the edge, requests reach the app over plaintext HTTP; without this flag Django thinks every request is insecure and `SECURE_SSL_REDIRECT` sends it into an infinite `301` redirect loop. Only enable it behind a proxy that overwrites any client-supplied `X-Forwarded-Proto` — otherwise the header is spoofable.
   - `SECURE_SSL_REDIRECT` (default `true` in production): redirect all HTTP requests to HTTPS. Set to `false` only as an incident kill-switch (e.g. to break a redirect loop while debugging proxy config).
   - `SECURE_HSTS_SECONDS` (default `3600` = 1 hour): HSTS max-age. HSTS is a hard-to-reverse browser commitment — if HTTPS breaks, clients that cached the header are locked out until it expires. Start conservative and ramp the value up only once HTTPS is proven stable, e.g. **1 hour → 1 day → 1 week → 1 year (`31536000`)**.
   - `SECURE_HSTS_INCLUDE_SUBDOMAINS` (default `false`) and `SECURE_HSTS_PRELOAD` (default `false`): keep both off until HSTS has run at a long max-age with zero HTTPS incidents; preload is effectively irreversible.

   > Health-check note (deployment): with `SECURE_SSL_REDIRECT` on, a platform health check that hits the app over internal HTTP without an `X-Forwarded-Proto: https` header will get a `301` and may be marked unhealthy. Mitigate by exempting the health path (`SECURE_REDIRECT_EXEMPT = [r"^healthz$"]`) or by pointing the health check at the public HTTPS domain.

7. Before starting the server, fetch the coins from the CoinGecko API and populate the database:

   ```bash
   python manage.py sync_supported_coins
   ```

   You must run this at least once before starting the server.

8. Start the scheduler in a separate foreground process when you want recurring catalog refreshes and scheduler cleanup:

   ```bash
   python manage.py runapscheduler
   ```

   This custom command starts an APScheduler instance that fetches the listed coins from CoinGecko every 2 hours and
   5 minutes to keep the database updated.

## Running the Server

To start the development server, run:

```bash
python manage.py runserver
```

Then open your browser and navigate to `http://localhost:8000`.

## Database Strategy

PostgreSQL is the **only** supported database for local development, tests, and
production. There is no SQLite fallback or separate lightweight test settings
path — this is a deliberate choice:

- The app depends on PostgreSQL-specific behavior and on financial calculations
  where engine differences (numeric/`Decimal` handling, constraints) could let
  tests pass on SQLite while failing in production.
- Running tests against the real engine keeps test and production behavior
  aligned, with no divergence to reason about.

The cost is that a running PostgreSQL instance is required even for tests. See
step 2 of Installation for the role/database setup, including the `CONNECT`
privilege on the `postgres` database that Django needs to create the temporary
`test_*` database.

## Static Files

The app has a small, hand-maintained set of static assets — the project's
`static/style.css` plus Django admin's bundled files — so it serves them from the
web process itself using [WhiteNoise](https://whitenoise.readthedocs.io/) rather
than a separate CDN or reverse proxy.

- **Development:** `runserver` serves assets directly from `STATICFILES_DIRS` via
  the staticfiles finders. No extra step is needed.
- **Production:** run `python manage.py collectstatic` to gather assets into
  `STATIC_ROOT` (`staticfiles/`, git-ignored). WhiteNoise then serves them
  compressed and content-hashed (`CompressedManifestStaticFilesStorage`) with
  far-future, immutable cache headers.

Because the manifest storage returns unhashed URLs while `DEBUG` is on, you do
**not** need to run `collectstatic` for local development.

## Running Tests

Tests run against a temporary `test_*` PostgreSQL database that Django creates
and drops automatically, so a running PostgreSQL instance and the `CONNECT`
privilege from Installation step 2 are required. To execute the test suite, run:

```bash
python manage.py test
```

## Development Tools

Ruff and pre-commit are installed by `requirements-dev.txt` (Installation step 1);
they are dev-only and are not part of the runtime `requirements.txt`.

Ruff is the code-quality tool for this project:

```bash
ruff check .                   # lint
ruff check --select I --fix .  # sort imports
ruff check --fix .             # apply safe lint fixes, including imports
ruff format .                  # format
```

Install Git hooks after installing the project dependencies:

```bash
pre-commit install
```

The commit hook sorts imports and formats Python files with Ruff. The push hook
runs the Django test suite via `scripts/pre_push_tests.sh`, which uses
`venv/bin/python` when present and otherwise falls back to the active `python`.
It needs the PostgreSQL test database privileges described above.

To run the hooks manually:

```bash
pre-commit run --all-files
pre-commit run --hook-stage pre-push --all-files
```

## Verifying Your Setup

After completing Installation, run the verification script to confirm the
project is correctly configured from a clean checkout:

```bash
scripts/verify_setup.sh
```

It runs the setup steps in order and stops at the first failure, so a broken
step is easy to spot:

1. `manage.py check` — settings import and system checks pass.
2. `manage.py migrate` — the database is reachable and migrations apply.
3. `manage.py createcachetable` — the DB-backed cache table exists.
4. `manage.py test` — the suite passes against real PostgreSQL.

Every step is idempotent, so the script is safe to re-run. It uses the
checked-in `venv/bin/python` if present (otherwise the active `python`) and
requires the environment variables and PostgreSQL access described above. Pass
arguments through to the test step to narrow the run, e.g.
`scripts/verify_setup.sh coins`.
