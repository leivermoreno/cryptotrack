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
   pip install -r requirements.txt
   ```

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

   - `SECRET_KEY`: Django secret key
   - `CSRF_TRUSTED_ORIGINS`: comma-separated list of trusted origins (e.g., `https://example.com`)
   - `COINGECKO_KEY`: API key for CoinGecko
   - `DATABASE_URI` (optional): Database URL (e.g., `postgres://user:password@host:5432/dbname`). Defaults to `postgres://crypto_track@/crypto_track`.

   The project supports `.env` files. You can create a `.env` file in the root directory and add the variables.

7. Before starting the server, fetch the coins from the CoinGecko API and populate the database:

   ```bash
   python manage.py runapscheduler --run-now
   ```

   You must run this at least once before starting the server. This custom command starts an APScheduler instance that
   fetches the listed coins from CoinGecko every two hours to keep the database updated. The `--run-now` flag triggers
   the job immediately.

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
