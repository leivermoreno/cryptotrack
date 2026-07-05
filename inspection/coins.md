# Coins App Inspection

## Scope

Inspected the `coins/` app and shared wiring needed to understand it: `crypto_track/settings.py`, `crypto_track/urls.py`, `templates/base.html`, `static/style.css`, `requirements.txt`, `README.md`, common pagination/template utilities, and the direct `portfolio` integration points that consume coin data. This is inspection only; no application code was changed.

## What the App Does

The `coins` app is the market-data and watchlist surface for CryptoTrack.

- Shows a public cryptocurrency market table at `/`, backed by CoinGecko market data (`coins/views.py:23`, `coins/services.py:48`).
- Supports navbar search by locally stored coin name or symbol, then enriches matching CoinGecko ids with live market data (`coins/views.py:50`, `coins/templates/coins/partials/search_form.html:1`).
- Lets authenticated users toggle active coins into a watchlist (`coins/views.py:79`, `coins/models.py:15`).
- Shows an authenticated watchlist page with current market data for saved coins (`coins/views.py:96`).
- Feeds portfolio transaction entry from the coin table via the CoinGecko id (`coins/templates/coins/partials/coins_table.html:64`, `portfolio/urls.py:11`).
- Provides a scheduler command intended to seed and refresh the local supported-coin catalog from CoinGecko (`coins/management/commands/runapscheduler.py:14`).

The local database does not store market prices. It stores the supported coin catalog and user watchlist rows; current prices, rank, ATH, market cap, volume, and price-change percentages are fetched from CoinGecko when views need them.

## Architecture and Wiring

- `coins.apps.CoinsConfig` is installed in `INSTALLED_APPS` (`crypto_track/settings.py:47`).
- The project root URL includes `coins.urls` at `""`, making `coins:index` the home page (`crypto_track/urls.py:23`, `coins/urls.py:10`).
- `templates/base.html` links the brand and Home nav item to `coins:index`, conditionally exposes the Watchlist link for authenticated users, and includes the coin search form in the global navbar (`templates/base.html:21`, `templates/base.html:26`, `templates/base.html:47`).
- CoinGecko configuration is project-level: `COINGECKO_ENDPOINT` and required `COINGECKO_KEY` are read in settings (`crypto_track/settings.py:156`). Cache timeouts also live in settings (`crypto_track/settings.py:108`).
- The default cache backend is Django database cache at table `cache`, so deployment requires `createcachetable` as the README states (`crypto_track/settings.py:101`, `README.md:52`).
- App-local constants are in `coins/settings.py`: market page size is 100, watchlist page size is 10, and sort names map to CoinGecko response keys (`coins/settings.py:1`).

The app is small and mostly function-based: views orchestrate request parsing, model queries, service calls, and template rendering directly. There is no separate form layer for search/watchlist and no dedicated CoinGecko client object.

## Models, Admin, and Migrations

### `Coin`

`Coin` stores CoinGecko catalog identity and display data (`coins/models.py:5`):

- `cg_id`: unique CoinGecko id, max length 100.
- `name`: display name, max length 200.
- `symbol`: display symbol, max length 50.
- `is_active`: boolean flag added in migration `0002`, defaulting to true (`coins/migrations/0002_coin_is_active.py:13`).
- `__str__` returns the name (`coins/models.py:11`).

`Coin` is the integration point for `portfolio.PortfolioTransaction` via `ForeignKey(Coin, on_delete=CASCADE)` (`portfolio/models.py:11`). Deleting a `Coin` would delete related portfolio transactions and watchlist rows; deactivation is the safer operational mechanism and is already used by query filters.

### `Watchlist`

`Watchlist` joins a Django auth `User` to a `Coin` (`coins/models.py:15`):

- Foreign keys cascade on user or coin deletion (`coins/models.py:16`).
- A uniqueness constraint prevents duplicate `(coin_id, user_id)` rows (`coins/models.py:25`, `coins/migrations/0001_initial.py:60`).
- `get_coin_ids_for_user(user_id)` returns active watchlisted CoinGecko ids (`coins/models.py:19`).

The model uses `django.contrib.auth.models.User` directly instead of `settings.AUTH_USER_MODEL` (`coins/models.py:2`). That is workable for the current project but makes future custom-user refactors harder.

Watchlist rows have no timestamp or explicit ordering. Watchlist pagination therefore depends on database default ordering, which is not stable or meaningful (`coins/views.py:99`).

### Admin

Only `Coin` is registered in admin (`coins/admin.py:6`). It lists id, name, symbol, and active status; supports searching by name/symbol; and orders by id (`coins/admin.py:8`).

The admin fieldset exposes only `name`, `symbol`, and `is_active`, with `name` and `symbol` read-only (`coins/admin.py:11`). `cg_id` is required on the model but omitted from the admin form. This makes sense if admin is intended only for toggling `is_active` on scheduler-created coins, but it should be made explicit. If admins are expected to create or repair coin records manually, the current admin form is incomplete.

`Watchlist` is not registered in admin. That limits support/debug visibility for user watchlist state.

## CoinGecko Service Workflow

`coins/services.py` is responsible for HTTP calls, cache usage, page counts, and local sorting.

### HTTP Session

- A thread-local `requests.Session` is created lazily (`coins/services.py:13`).
- The CoinGecko demo API key is attached as `x-cg-demo-api-key` (`coins/services.py:19`).
- The API key and endpoint are read into module-level constants when `coins.services` imports (`coins/services.py:8`).

Risks:

- No request timeout is set, so a slow CoinGecko request can hang a web request or scheduler run.
- No `raise_for_status`, retry policy, or response-shape validation exists. Rate limits, HTML error pages, or malformed JSON will surface as unhandled exceptions or bad cached data.
- Because `COINGECKO_KEY = os.environ["CRYPTO_COINGECKO_KEY"]` is required in settings, many commands can fail at import time if the environment variable is missing (`crypto_track/settings.py:157`).
- `python-dotenv` is installed, and README says `.env` files are supported, but settings do not call `load_dotenv()` (`requirements.txt:18`, `README.md:69`).

### Supported Coin List

`get_supported_coin_list()` calls `GET {COINGECKO_ENDPOINT}coins/list` with `status=active` and caches the JSON under `supported_coin_list` for `CACHE_SUPPORTED_COINS_TIMEOUT` seconds (`coins/services.py:25`, `crypto_track/settings.py:108`).

`get_coin_count()` and `get_page_count()` derive market page count from this supported list, not from the local `Coin` table and not from the `/coins/markets` response (`coins/services.py:40`). That keeps the public market independent of whether the scheduler has populated the DB, but it also means page count depends on CoinGecko availability.

### Market Data

`get_coin_list_with_market(page, sort, direction, ids=None)` calls `GET {COINGECKO_ENDPOINT}coins/markets` with:

- `vs_currency=usd`
- `order=market_cap_desc`
- `page`
- `per_page=RESULTS_PAGE`
- `price_change_percentage=24h,7d`
- optional comma-joined `ids` (`coins/services.py:56`)

When `ids` is `None`, raw page data is cached by page only as `coin_list_page_{page}` for 60 seconds (`coins/services.py:53`, `crypto_track/settings.py:109`). When ids are provided, data is not cached to avoid too many cache keys (`coins/services.py:49`).

Important behavior: sorting is local to the returned data (`coins/services.py:77`). For the index, CoinGecko always returns a market-cap-desc page first, and the app then sorts only that page in Python. Sorting by price, ATH, volume, or market cap is therefore not global across the full market. Search and watchlist have the same issue because ids are paginated before market sorting (`coins/views.py:62`, `coins/views.py:100`). This is likely surprising to users.

Other service notes:

- `cache.has_key()` is used instead of a single `cache.get()`/sentinel pattern (`coins/services.py:26`, `coins/services.py:53`).
- `get_supported_coin_list()` calls `res.json()` twice on a cache miss (`coins/services.py:34`, `coins/services.py:37`).
- `_sort_coin_list()` mutates the list passed into it (`coins/services.py:83`). That is manageable today but easy to trip over if the cache backend or caller behavior changes.
- Missing sort values are coerced to `0`, which can mix unknown values with real zeros (`coins/services.py:83`).

## Scheduled Command Workflow

`python manage.py sync_supported_coins` is the one-shot way to seed the coin catalog before starting the server. `python manage.py runapscheduler` is the long-running scheduler process. The scheduler command:

- Creates a blocking APScheduler using Django's time zone (`coins/management/commands/runapscheduler.py:45`).
- Uses `DjangoJobStore` so scheduler job metadata lives in the database (`coins/management/commands/runapscheduler.py:48`).
- Registers `sync_supported_coins_job()` as an interval job (`coins/management/commands/runapscheduler.py:51`).
- Registers weekly cleanup of old `DjangoJobExecution` records (`coins/management/commands/runapscheduler.py:60`).

`coins.sync.sync_supported_coins()` pulls CoinGecko's cached/live active supported list, upserts local `Coin` labels, reactivates returned coins, and soft-deactivates currently active local coins whose `cg_id` is absent from a successful fetch (`coins/sync.py:4`). It returns counts for created, updated, deactivated, skipped, and failed rows; malformed fetched rows with missing/blank `id`, `name`, or `symbol` are counted as failed and do not abort the sync. It does not delete rows, so existing watchlist and portfolio references can continue pointing at historical coin records.

Resolved scheduler interval bug: `SUPPORTED_COINS_TIMEOUT` is configured in seconds as `3600 * 2`, and the scheduler now passes `SUPPORTED_COINS_SYNC_INTERVAL_SECONDS = SUPPORTED_COINS_TIMEOUT + 5 * 60` to APScheduler as `seconds=` (`crypto_track/settings.py:188`, `coins/management/commands/runapscheduler.py:17`). The recurring sync cadence is 7,500 seconds, or 2 hours plus 5 minutes.

Operational risks:

- The scheduler is a blocking long-running process separate from the web server.
- `max_instances=1` prevents overlap inside one scheduler process, not across accidentally duplicated scheduler processes.
- Whole-call CoinGecko failures are logged and skipped; successful syncs log created, updated, deactivated, skipped, and failed row counts.
- The local catalog is refreshed by upserting returned active rows and soft-deactivating active rows absent from a successful active-list fetch.

## Views, URLs, Templates, and User Flows

### URL Map

`coins/urls.py` defines:

- `/` -> `render_index`, name `coins:index` (`coins/urls.py:11`).
- `/add_remove_to_watchlist/<str:cg_id>/` -> `add_remove_to_watchlist`, name `coins:add_remove_to_watchlist` (`coins/urls.py:12`).
- `/watchlist/` -> `render_watchlist`, name `coins:watchlist` (`coins/urls.py:17`).
- `/search/` -> `render_search`, name `coins:search` (`coins/urls.py:18`).

### Index Flow

`render_index` validates common `page`, `sort`, and `direction` params, computes page count from CoinGecko's supported list, fetches one market page, and optionally loads the authenticated user's active watchlist ids (`coins/views.py:23`).

`coins/index.html` renders the shared coin table and a custom previous/next block (`coins/templates/coins/index.html:9`, `coins/templates/coins/index.html:11`). The pagination links only preserve `page`; they drop current `sort` and `direction` (`coins/templates/coins/index.html:13`). Sorting links in the table do preserve page/sort/direction via `sort_link`.

### Search Flow

The navbar search submits to `/search/` with a `search` query parameter (`coins/templates/coins/partials/search_form.html:1`). Empty search redirects to the market index (`coins/views.py:52`).

For non-empty search, the app:

1. Queries active local `Coin` rows where name or symbol contains the search string (`coins/views.py:56`).
2. Computes page count from the number of matching ids (`coins/views.py:60`).
3. Paginates the ids locally (`coins/views.py:62`).
4. Fetches market data from CoinGecko for ids on the current page (`coins/views.py:63`).
5. Renders `coins/search.html`, which includes the shared table and common pagination partial (`coins/templates/coins/search.html:6`).

Search depends on the scheduler-populated local catalog. If the local `Coin` table is empty or stale, search will miss coins even though the index can still display CoinGecko market data.

The search view is public. It always calls `Watchlist.get_coin_ids_for_user(request.user.id)` without first checking authentication (`coins/views.py:64`). With Django's anonymous user this likely evaluates to an empty `user_id=None` query, but the index handles this more explicitly (`coins/views.py:30`).

### Watchlist Flow

`render_watchlist` is login-required and uses the active watchlist helper to get CoinGecko ids (`coins/views.py:96`). It paginates ids by `WATCHLIST_COINS_PAGE = 10`, fetches market data for the current page, and renders `coins/watchlist.html` (`coins/views.py:100`, `coins/templates/coins/watchlist.html:6`).

Inactive coins are filtered out by `Watchlist.get_coin_ids_for_user`, so they disappear from the watchlist UI without deleting the watchlist row (`coins/models.py:21`). That is a reasonable soft-hide behavior but should be made visible in admin/support tooling.

### Add/Remove Flow

The shared table renders a POST form per row to toggle watchlist membership (`coins/templates/coins/partials/coins_table.html:52`). The URL argument is `coin.id` from the CoinGecko market payload, which is actually the CoinGecko id, not the database primary key (`coins/templates/coins/partials/coins_table.html:52`). The view parameter is named `cg_id`, so the behavior is correct but the template naming is confusing.

`add_remove_to_watchlist`:

- Requires login and POST (`coins/views.py:79`).
- Gets an active `Coin` by `cg_id` (`coins/views.py:83`).
- Creates a watchlist row or deletes the existing row (`coins/views.py:84`).
- Silently ignores missing/inactive coins (`coins/views.py:89`).
- Redirects to `request.POST["next"]` or the market index (`coins/views.py:92`).

Security risk: `next` is trusted directly. A crafted POST can redirect an authenticated user to an external URL. Use Django's allowed-host validation before redirecting user-provided destinations.

### Shared Table Partial

`coins/templates/coins/partials/coins_table.html` displays rank, coin, price, 24h/7d changes, ATH, volume, market cap, watchlist action, and portfolio action.

It uses common formatting filters for amounts/percentages/classes (`coins/templates/coins/partials/coins_table.html:1`, `common/templatetags/common_extras.py:46`). It also uses `sort_link` for sortable headers (`coins/templates/coins/partials/coins_table.html:10`, `common/templatetags/common_extras.py:76`).

Polish issues:

- The table is not wrapped in Bootstrap's `table-responsive`, so it will be difficult on small screens.
- Watchlist controls are text links/buttons rather than visually distinct stateful controls.
- Unauthenticated users see watchlist and portfolio actions, then are redirected after clicking. That works, but the UX is not explicit.
- Symbol display uses CoinGecko's raw symbol value and does not normalize casing (`coins/templates/coins/partials/coins_table.html:39`).

## Pagination and Common Utilities

`validate_common_params(ALLOWED_SORTS)` wraps the coins views and redirects to the same path when page/sort/direction are invalid (`common/decorators/views.py:6`, `coins/views.py:19`). `get_common_params(default_sort="rank", default_direction="asc")` parses page/sort/direction and clamps too-high pages to the last page (`common/utils.py:7`, `coins/views.py:20`).

This gives all coins views a consistent validation baseline. Remaining issues:

- The helper does not redirect canonical high page URLs; it silently renders the clamped page (`common/utils.py:11`).
- The decorator rejects partial sort params such as `?sort=price` without direction (`common/decorators/views.py:23`).
- Index uses custom pagination instead of `common/partials/pagination.html`, so it loses sort/direction on next/previous links (`coins/templates/coins/index.html:13`).
- The common pagination partial is not truly generic because it always renders "Back to Market" linking to `coins:index` (`common/templates/common/partials/pagination.html:2`).
- `sort_link` and pagination links manually concatenate query strings (`common/templatetags/common_extras.py:87`, `common/templates/common/partials/pagination.html:5`). Search terms and `next` values are not URL-encoded through a structured query builder.
- Sorting is applied after pagination for index/search/watchlist, so pagination and sorting do not compose as users generally expect.

## Tests

`coins/tests.py` contains basic model and view tests:

- Coin creation, string representation, and default `is_active` (`coins/tests.py:8`).
- Watchlist uniqueness and active coin id helper (`coins/tests.py:15`).
- Index/search/watchlist view status/template/context smoke tests (`coins/tests.py:31`).
- Authenticated add/remove toggle and unauthenticated redirects (`coins/tests.py:56`).

Gaps:

- View tests do not mock `coins.services`, so index/search/watchlist can make real CoinGecko calls through `get_page_count()` and `get_coin_list_with_market()` (`coins/views.py:26`, `coins/views.py:63`, `coins/views.py:106`).
- Tests require settings import to succeed, which currently requires `CRYPTO_COINGECKO_KEY` (`crypto_track/settings.py:157`).
- No tests cover CoinGecko error handling, cache behavior, sort semantics, scheduler behavior, inactive coins disappearing from watchlist/search/portfolio, admin behavior, `next` redirect safety, or pagination preserving query params.
- Portfolio tests also depend indirectly on the live coin market service through `portfolio.services.get_portfolio_overview_data()` (`portfolio/services.py:4`, `portfolio/tests.py:60`).

Tests were not executed during this inspection because they are not isolated from network/environment dependencies.

## Key Risks, Bugs, and Technical Debt

1. Scheduler interval unit bug was fixed in step 6.4: the refresh job now runs every 7,500 seconds, not every 5.2 days (`coins/management/commands/runapscheduler.py:17`).
2. Live HTTP calls have no timeout, retry, status handling, schema validation, or graceful fallback (`coins/services.py:29`, `coins/services.py:57`).
3. `CRYPTO_COINGECKO_KEY` is mandatory at settings import time, making unrelated commands fragile in unconfigured environments (`crypto_track/settings.py:157`).
4. README claims `.env` support, but settings do not load `.env` files (`README.md:69`).
5. Sorting is page-local, not global, across index/search/watchlist (`coins/services.py:74`).
6. Search and watchlist paginate ids before market sorting, so sorted pages can be inconsistent across the full result set (`coins/views.py:62`, `coins/views.py:100`).
7. User-provided `next` is trusted in watchlist toggles, creating an open-redirect risk (`coins/views.py:92`).
8. The coin sync job now upserts returned rows, reactivates returned inactive rows, deactivates active rows missing from a successful fetch, and logs result counts (`coins/sync.py:4`, `coins/management/commands/runapscheduler.py:22`).
9. Admin is incomplete for manual creation/repair and does not expose Watchlist records (`coins/admin.py:6`).
10. Watchlist ordering is undefined because the model has no timestamp/default ordering (`coins/models.py:15`).
11. Query-string building is duplicated and manual across templates/tags (`common/templatetags/common_extras.py:90`).
12. Test suite is coupled to live external services and environment variables (`coins/tests.py:40`).
13. The UI is minimally styled and the wide market table is not mobile-friendly (`static/style.css:1`, `coins/templates/coins/partials/coins_table.html:3`).

## Refactor and Polish Opportunities

- Introduce a `CoinGeckoClient` or service object with injected settings, timeouts, retries/backoff, `raise_for_status`, structured errors, response normalization, and narrow methods such as `list_supported_coins()` and `get_markets(ids=None, order=..., page=...)`.
- Move scheduler sync logic into a reusable domain service and keep the management command thin. Add a one-shot `sync_coins` command separate from the blocking scheduler path.
- Scheduler interval fixed in step 6.4 by passing an explicitly named seconds value to APScheduler.
- Catalog sync now upserts/updates, reactivates returned rows, and deactivates coins no longer returned as active. Future options include `last_seen_at` or `source_status` if more auditability is needed.
- Make model relationships more future-proof: use `settings.AUTH_USER_MODEL`, add `related_name`s, add timestamps to `Watchlist`, and define deterministic ordering.
- Clarify id naming at the template boundary. Market payload `id` should be exposed as `cg_id` before rendering or referenced explicitly as a CoinGecko id.
- Validate `next` redirects with allowed-host checks and fall back to a safe named route.
- Replace manual query-string concatenation with a helper based on `QueryDict`/`urlencode`. Preserve sort/direction/search consistently in pagination.
- Decide the intended sort semantics. Either use CoinGecko-supported API ordering for global market sorting, fetch and sort the full relevant search/watchlist set before paginating where feasible, or label the UI as current-page sorting only.
- Make `common/partials/pagination.html` actually generic by accepting optional `back_url`/`back_label`, or move the market-specific back link into coins templates.
- Register `Watchlist` in admin and make `CoinAdmin` either explicitly read-only except `is_active` or fully capable of safe manual repair with `cg_id` visible.
- Mock `coins.services` in view tests. Add unit tests for service behavior with mocked `requests.Session`, scheduler sync behavior, inactive coin filtering, open-redirect defense, and query-param preservation.
- Improve empty/error states: clear message when CoinGecko is unavailable, when search cannot work because the catalog is empty, and when a logged-out user clicks watchlist/portfolio actions.
- Wrap the market table in responsive markup and improve action affordances while keeping the existing Bootstrap 5 baseline.
