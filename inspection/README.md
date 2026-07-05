# CryptoTrack Inspection Overview

This folder contains the first-pass inspection reports for the existing
CryptoTrack Django application. The reports are meant to establish the current
state before a full refactor and polish pass.

## Reports

- `inspection/accounts.md`: registration, login/logout integration, account
  templates, and authentication wiring.
- `inspection/coins.md`: coin catalog, CoinGecko integration, watchlist,
  search, index, scheduled sync, and market-data flows.
- `inspection/portfolio.md`: transaction model, portfolio holdings,
  unrealized profit/loss calculations, transaction CRUD, and overview screens.
- `inspection/common.md`: shared query-parameter validation, pagination,
  formatting template tags, and reusable partials.

## Project Shape

CryptoTrack is a server-rendered Django app using PostgreSQL, Bootstrap 5,
django-crispy-forms, APScheduler, django-apscheduler, and CoinGecko market
data. The root URL config in `crypto_track/urls.py` mounts:

- `/`: `coins.urls`
- `/accounts/`: `accounts.urls`
- `/portfolio/`: `portfolio.urls`
- `/admin/`: Django admin

The global template shell is `templates/base.html`. It provides navigation,
authentication-sensitive links, messages, and a shared coin search form. Static
styling is currently minimal in `static/style.css`.

## Application Responsibilities

`coins` is the market-data and watchlist app. It owns the `Coin` and
`Watchlist` models, calls CoinGecko from `coins/services.py`, renders the home
table and search results, and provides authenticated add/remove watchlist
actions.

`portfolio` is the holdings and transaction app. It owns
`PortfolioTransaction`, lets users create/edit/delete buy and sell records, and
builds a portfolio overview by combining database transactions with live
CoinGecko market data.

`accounts` is a thin wrapper around Django auth. It adds registration via
`UserCreationForm`, includes Django auth URL patterns for login/logout, and
uses the default `auth.User` model.

`common` contains shared presentation and request helpers: sorting direction,
query-parameter validation, pagination markup, number formatting, and sort-link
template tags.

## Main Workflows

1. Coin sync: `python manage.py runapscheduler --run-now` calls CoinGecko's
   supported coin list endpoint and bulk-creates missing `Coin` rows.
2. Browse market: the index page calls CoinGecko `coins/markets`, optionally
   sorts results locally, and marks rows already present in the current user's
   watchlist.
3. Search: the app searches local `Coin` rows by name or symbol, paginates the
   matching CoinGecko IDs, then fetches current market data for the page.
4. Watchlist: authenticated users toggle `Watchlist` rows. The watchlist page
   fetches current market data for watched CoinGecko IDs.
5. Portfolio transactions: authenticated users record buys and sells for active
   coins. Sells are validated against current balance in the view.
6. Portfolio overview: positive-balance coin IDs are calculated from
   transactions, current prices are fetched from CoinGecko, FIFO lots are
   reconstructed, and unrealized P/L plus allocation percentages are rendered.

## Cross-Cutting Findings

- Runtime setup is brittle. Importing settings requires
  `CRYPTO_COINGECKO_KEY`, and production mode also requires
  `CSRF_TRUSTED_ORIGINS`.
- Local verification could not run in the active interpreter because Django is
  not installed. `env CRYPTO_COINGECKO_KEY=dummy python manage.py check`
  failed with `ModuleNotFoundError: No module named 'django'`.
- Tests are present for coins and portfolio, but important view tests are
  coupled to live CoinGecko service calls unless patched/mocked.
- External HTTP calls have no explicit timeouts, response status handling,
  retry policy, schema validation, or user-facing degradation path.
- Query-string handling is split across decorators, helpers, template tags, and
  views. This makes pagination and sorting behavior hard to reason about.
- Several paths use broad silent failure patterns (`except ...: pass`) that hide
  invalid IDs, missing coins, and failed operations.
- Business rules are partly in views. Sell validation, deletion constraints,
  FIFO holdings, portfolio metrics, and market-data joins should be consolidated
  behind clearer service/domain APIs.
- The UI is functional but very lightly polished: mostly Bootstrap defaults,
  small global CSS, limited empty/error states, and text-only table actions.

## Suggested Refactor Sequence

1. Recreate a reproducible dev/test environment and make settings importable
   with safe development defaults.
2. Add service-level tests with mocked CoinGecko responses and isolate view
   tests from the network.
3. Stabilize external API behavior: timeouts, status checks, typed return
   shapes, cache policy, and graceful fallbacks.
4. Normalize common request state for page/sort/direction/search and make
   pagination reusable without manual query-string construction.
5. Move portfolio transaction invariants out of views and into tested domain
   services/forms/model constraints.
6. Improve authentication/account UX, redirects, messages, and account-related
   tests.
7. Polish the UI around dense portfolio/market workflows: table controls,
   empty states, action affordances, responsive behavior, and error handling.

## Notes

This inspection pass only added files under `inspection/`. No application code
was modified.
