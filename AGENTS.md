# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Commands

All commands assume the virtualenv is active (`source venv/bin/activate`) and require env vars set (see Environment below — settings will not import without `SECRET_KEY` and `CSRF_TRUSTED_ORIGINS`).

```bash
python manage.py migrate              # apply DB migrations
python manage.py createcachetable     # create the DB-backed cache table (required once)
python manage.py runapscheduler --run-now   # populate Coin table from CoinGecko + start the sync scheduler
python manage.py runserver            # dev server at http://localhost:8000
python manage.py test                 # full test suite
python manage.py test coins           # single app
python manage.py test coins.tests.CoinModelTest.test_coin_creation_and_str   # single test
ruff check .                          # lint
ruff check --select I --fix .         # sort imports
ruff check --fix .                    # apply safe lint fixes, including imports
ruff format .                         # format
pre-commit install                    # install pre-commit and pre-push hooks
pre-commit run --all-files            # run commit hooks across the repo
pre-commit run --hook-stage pre-push --all-files   # run push hooks
```

`runapscheduler --run-now` must be run at least once before the app is usable: the `Coin` table is empty otherwise and search/watchlist/portfolio all resolve local `Coin` rows. It runs a **blocking** scheduler (foreground process) that also re-syncs the coin list on an interval.

Tests need the DB user to have CONNECT privilege on the `postgres` database (Django creates a `test_*` database).

## Environment

Loaded from a `.env` file in the project root (via python-dotenv) or the process environment. See `.env.example`.

- `SECRET_KEY` — **required** (`settings.py` reads it at module load, no fallback). `manage.py check` fails without it.
- `CSRF_TRUSTED_ORIGINS` — **required** (comma-separated list of origins), read at module load.
- `COINGECKO_KEY` — optional at import (defaults to `""`), but required at runtime for any CoinGecko request. A system check (`coins.W001`) warns when it is unset.
- `DATABASE_URI` — optional, parsed by `dj_database_url`. Defaults to `postgres://crypto_track@/crypto_track`.
- `PYTHON_ENV` — `DEBUG` is on unless this equals `production`.

## Architecture

Server-rendered Django 5.2 app (Bootstrap 5 + crispy-forms, no JS framework). Four local apps under a `crypto_track` project. CoinGecko is the single external data source; PostgreSQL is the only supported DB.

### App responsibilities
- **`coins`** — market data + watchlist. Owns `Coin` (mirror of CoinGecko's coin list, keyed by `cg_id`; `is_active` soft-deactivates delisted coins) and `Watchlist`. All CoinGecko HTTP lives in `coins/services.py`.
- **`portfolio`** — buy/sell transactions (`PortfolioTransaction`) and the portfolio overview. `portfolio/services.py` reconstructs holdings and computes unrealized P/L.
- **`accounts`** — thin wrapper over Django auth (registration + built-in login/logout URLs, default `auth.User`).
- **`common`** — shared request/presentation helpers used across apps: param validation decorator, param-reading helper, pagination partial, and number/sort template tags.

### CoinGecko integration & caching (`coins/services.py`)
- Uses a thread-local `requests.Session` with the API key header. No timeouts, status checks, or retries — calls can raise or return unexpected shapes.
- Caching is **DB-backed** (`DatabaseCache`, the `cache` table). The supported coin list is cached for 2h; per-page market data for 60s (`CACHE_*_TIMEOUT` in `settings.py`).
- `get_coin_list_with_market(page, sort, direction, ids=None)` is the central market-data call. When `ids` is passed (search/watchlist/portfolio), results are **not cached** (to avoid cache explosion) and sorting is done in Python via `_sort_coin_list`.

### Portfolio math (`portfolio/services.py`)
- `build_holdings` reconstructs open lots per coin using **FIFO** (a `deque` per coin; sells consume oldest lots first).
- `get_portfolio_overview_data` joins FIFO holdings with live CoinGecko prices to compute average buy price, unrealized P/L, and allocation percentages.
- Balance/sell invariants currently live partly in the views (e.g. `create_portfolio_transaction` rejects sells exceeding balance; `delete_portfolio_transaction` blocks deletes that would make balance negative).

### Sorting / pagination convention (important, and split across layers)
Query-string handling for `page`/`sort`/`direction` is spread across three pieces — know all three when touching list views:
1. `common/decorators/views.py::validate_common_params(allowed_sorts)` — a decorator that **redirects** on invalid params. Instantiated per-view with that view's allowed sorts.
2. `common/utils.py::get_common_params(default_sort, default_direction)` — returns a reader function that pulls clamped `page`/`sort`/`direction` from the request.
3. `common/templatetags/common_extras.py::sort_link` — builds sortable column header links; other tags there (`format_number`, `format_amount`, `format_percentage`, `percentage_change_class`) do display formatting.

Each app defines its own `settings.py` (e.g. `coins/settings.py`, `portfolio/settings.py`) holding `ALLOWED_SORTS`, page sizes, and defaults — these are plain module constants, **not** Django settings. `ALLOWED_SORTS` maps a UI sort key to the underlying field (CoinGecko JSON key in `coins`, ORM field in `portfolio`).

Index/search pagination is manual (`get_page_count` / `math.ceil`) because the total set lives in the external API, not the DB.

## Notes
- Several handlers use broad `except (Coin.DoesNotExist, ...): pass` and silently redirect — intentional current behavior.
