# Portfolio App Inspection

Inspection date: 2026-06-30

Scope inspected: `portfolio/`, plus shared wiring and dependencies needed to understand it: `crypto_track/settings.py`, `crypto_track/urls.py`, `templates/base.html`, `static/style.css`, `requirements.txt`, `README.md`, and the relevant `coins` and `common` helpers used by portfolio views/templates.

## Executive Summary

The `portfolio` app lets authenticated users record cryptocurrency buy/sell transactions, view all transaction history, and view an overview of current holdings with cost basis, current market price, allocation, and unrealized profit/loss. It is small and mostly conventional Django: one model, one `ModelForm`, function-based views, app templates, shared pagination/sort helpers, and a service module for FIFO holding calculations.

The main refactor pressure points are correctness and isolation. Portfolio calculations depend synchronously on `coins.services.get_coin_list_with_market()` and therefore on CoinGecko behavior. Transaction validation lives in the view layer and only checks a narrow final-balance case, so edits, deletes, negative amounts/prices, race conditions, and oversold historical ledgers can produce invalid holdings. The overview FIFO calculator then assumes the ledger is valid and can crash on an oversell. Tests exist, but they are shallow and portfolio view tests appear to hit the external market service instead of mocking it.

No application code was changed during this inspection.

## What The App Does

- Records portfolio transactions for a user and coin through `PortfolioTransaction` in `portfolio/models.py`.
- Supports two transaction sides: `buy` and `sell`.
- Stores amount, price per coin, and auto-created timestamp.
- Shows a portfolio overview at `/portfolio/` with positive-balance coins only.
- Shows all transactions at `/portfolio/all/`.
- Lets users create, edit, and delete transactions through `/portfolio/add/...`, `/portfolio/edit/...`, and `/portfolio/delete/...`.
- Integrates with the market table in `coins/templates/coins/partials/coins_table.html`, where each market row has a "Portfolio Add" link to `portfolio:add_transaction_cg`.

The app tracks unrealized profit/loss only. Sell prices are displayed in transaction rows but are not used to calculate realized gains/losses.

## Architecture And Wiring

Project wiring:

- `portfolio.apps.PortfolioConfig` is installed in `crypto_track/settings.py` with `common`, `coins`, `accounts`, `crispy_forms`, `crispy_bootstrap5`, and `django_apscheduler`.
- `crypto_track/urls.py` mounts `portfolio.urls` at `/portfolio/`.
- `templates/base.html` shows a "Portfolio" nav link only for authenticated users and includes the shared coin search form on every page.
- `static/style.css` only sets a flex-column page shell; portfolio visual styling is otherwise Bootstrap classes in templates.
- `requirements.txt` pins Django 5.2.5, crispy forms/bootstrap 5, PostgreSQL driver, requests, APScheduler, and related dependencies.
- `README.md` describes the portfolio feature as buy/sell tracking plus unrealized profit/loss powered by CoinGecko.

Internal structure:

- `portfolio/models.py`: `PortfolioTransaction` model and query helpers.
- `portfolio/admin.py`: admin registration for transactions.
- `portfolio/forms.py`: `PortfolioTransactionForm`.
- `portfolio/services.py`: overview data assembly, FIFO holding calculation, portfolio metrics.
- `portfolio/views.py`: overview, all transactions, create/edit, and delete views.
- `portfolio/urls.py`: route names and URL patterns.
- `portfolio/settings.py`: local constants for allowed sort keys, default sort/direction, and page size.
- `portfolio/templates/portfolio/*.html`: overview, create/edit, all transactions, and transaction table partial.
- `portfolio/utils.py`: empty.

Data flow:

1. Users enter transactions through `PortfolioTransactionForm`.
2. Views save transactions with the authenticated user and selected `Coin`.
3. Transaction listing views use `PortfolioTransaction.get_for_user()` and shared sort/pagination helpers.
4. Overview asks `PortfolioTransaction.get_positive_coin_balance_ids()` for positive-balance coins.
5. `portfolio.services.get_portfolio_overview_data()` rebuilds remaining lots with FIFO, fetches current market data from `coins.services.get_coin_list_with_market()`, computes metrics, and returns template-ready dictionaries.

## Model, Admin, And Migrations

### `PortfolioTransaction`

Defined in `portfolio/models.py`.

Fields:

- `user`: `ForeignKey(User, on_delete=models.CASCADE)`.
- `coin`: `ForeignKey(Coin, on_delete=models.CASCADE)`.
- `type`: `CharField(max_length=4, choices=(("buy", "Buy"), ("sell", "Sell")))`.
- `amount`: `DecimalField(max_digits=20, decimal_places=8)`.
- `price`: `DecimalField(max_digits=20, decimal_places=8)`.
- `created`: `DateTimeField(auto_now_add=True)`.

Model helper methods:

- `get_for_user(user)` filters to the current user and active coins, annotates `total = amount * price`, and `select_related("coin")`.
- `get_coin_balance(user, coin)` aggregates buy amounts minus sell amounts for a user/coin.
- `get_positive_coin_balance_ids(user)` groups by coin, filters balances greater than zero, and returns `coin_id` plus `coin__cg_id`.

Model concerns:

- Uses `django.contrib.auth.models.User` directly instead of `settings.AUTH_USER_MODEL`.
- No positive-value validation for `amount` or `price`; negative and zero values are possible unless every caller adds validation.
- No database constraints for valid amount/price, valid transaction side beyond choices, or nonnegative user/coin balance.
- No indexes for common access patterns such as `(user, coin, created)` or `(user, created)`.
- No `Meta.ordering`; callers must remember ordering.
- No `__str__`, which makes shell/admin/debug output less useful.
- `get_coin_balance()` returns `None` when no matching transactions exist, which breaks first-sell validation in `portfolio/views.py`.
- The model hides inactive coins in all helper methods via `coin__is_active=True`; historical transactions for inactive coins disappear from portfolio pages and balance calculations.
- `on_delete=models.CASCADE` on `coin` means deleting a `Coin` deletes financial history. That may be acceptable for this app today, but it is risky for a ledger.

### Admin

Defined in `portfolio/admin.py`.

Current behavior:

- Lists id, user, coin name, type, amount, price, created.
- Filters by type and created date.
- Searches username and coin name.
- Orders newest first.
- Disables change permission with `has_change_permission()` returning `False`.

Admin concerns:

- `fieldsets` includes `created`, but `created` is an `auto_now_add` field and is not editable. If the admin add/change form is reachable, this can raise an admin form field error unless `created` is moved to `readonly_fields`.
- Change permission is disabled, but add/delete permissions are not explicitly documented in code. If the intent is audit-log immutability, admin permissions should be intentional across add/change/delete/view.
- There is no admin-level protection against invalid amounts/prices or overselling.

### Migrations

- `portfolio/migrations/0001_initial.py` creates `PortfolioTransaction` with `transaction_type`, amount, price, created, coin, and user.
- `portfolio/migrations/0002_rename_transaction_type_portfoliotransaction_type.py` renames `transaction_type` to `type`.

Migration concerns:

- The current public field name `type` is short but generic and shadows a Python builtin. A future refactor could use `side`, `kind`, or `transaction_type` with a `TextChoices` enum.
- There are no migrations for constraints or indexes.

## Forms

`PortfolioTransactionForm` in `portfolio/forms.py` is a bare `ModelForm` exposing only `type`, `amount`, and `price`.

Good:

- It correctly excludes `user` and `coin`; the view assigns both from trusted context.
- It is simple and works with crispy forms in `portfolio/templates/portfolio/create_transaction.html`.

Concerns:

- No form-level validation for `amount > 0` or `price > 0`.
- No form-level validation for sell balance. The view implements a partial check instead.
- No transaction-aware validation for edits. Editing an existing sell compares the new sell amount to a balance that already includes the old sell, which can reject valid edits. Editing a buy can reduce or flip the historical ledger into an oversold state because buy edits have no balance validation.
- No widgets, labels, decimal step hints, help text, or field ordering polish beyond Django defaults.
- No way to set actual trade date; `created` is system time, not transaction execution time.

## Services And Utilities

### `portfolio/services.py`

`get_portfolio_overview_data(user, cg_to_db_id_map)`:

- Calls `build_holdings()` for all positive-balance coin database ids.
- Calls `coins.services.get_coin_list_with_market(1, "rank", "asc", ids=...)`.
- For each returned market coin, calculates:
  - remaining amount,
  - remaining cost basis as `value`,
  - average buy price,
  - current price,
  - unrealized profit/loss,
  - unrealized profit/loss percentage.
- Calls `calculate_portfolio_metrics()` and adds `allocation_percentage` per coin.

`build_holdings(user, coin_ids)`:

- Loads transactions for the selected user and active coins ordered by `created`.
- Adds buy lots to a `deque`.
- Removes sell amounts from oldest lots using FIFO.
- Returns remaining lots grouped by CoinGecko id.

`calculate_portfolio_metrics(coin_list)`:

- Sums total invested cost basis, current market value, and unrealized profit/loss.

Service concerns:

- `build_holdings()` assumes valid history. If a sell appears before enough buy lots, `holdings[tx.coin.cg_id][0]` raises `IndexError`.
- The transaction ordering is only `created`; same-timestamp imports or data repairs would make FIFO nondeterministic. Use `created, id` or an explicit trade timestamp.
- `current_price = Decimal(coin["current_price"])` converts API values directly. If CoinGecko returns floats, this can preserve binary float artifacts; if it returns `None`, it raises.
- Positive-balance coins missing from the market API response silently disappear from the overview and metrics.
- `allocation_percentage` divides by `portfolio_value`. A non-empty portfolio with zero/unknown current prices can divide by zero.
- The field name `value` means cost basis in overview rows, while `portfolio_value` means current market value. That is easy to misread.
- Sell price is not used in overview metrics, so realized gain/loss is not tracked.
- Overview fetches current market data synchronously for the user's holdings and, because `coins.services` skips caching when `ids` are provided, this can hit CoinGecko on every overview request.
- There are no service tests for FIFO lots, partial sells, full sells, oversells, API-missing coins, or decimal edge cases.

### `portfolio/utils.py`

The file exists but is empty. It can be removed or given a clear purpose during refactor.

## Views, URLs, Templates, And Partials

### URLs

Defined in `portfolio/urls.py`:

- `/portfolio/` -> `portfolio_overview`, name `overview`.
- `/portfolio/add/<int:coin_id>` -> create transaction by database coin id.
- `/portfolio/add/<cg_id>/` -> create transaction by CoinGecko id.
- `/portfolio/edit/<int:coin_id>/<int:transaction_id>` -> edit transaction.
- `/portfolio/delete/<int:coin_id>/<int:transaction_id>` -> delete transaction.
- `/portfolio/all/` -> all transactions.

URL concerns:

- Trailing slash usage is inconsistent. `add/<cg_id>/` has a slash, while integer add/edit/delete routes do not.
- `/portfolio/add/123/` will match the `cg_id` route, while `/portfolio/add/123` matches the integer route. This is surprising behavior for numeric CoinGecko ids or manually typed URLs.
- Delete is correctly restricted to POST by the view, but the URL shape itself does not communicate that it is an action endpoint.

### `portfolio_overview`

Defined in `portfolio/views.py`.

Workflow:

1. Requires login.
2. Validates `sort` and `direction` against `OVERVIEW_ALLOWED_SORTS`.
3. Gets positive-balance coin ids from transaction aggregates.
4. Builds overview data through `get_portfolio_overview_data()`.
5. Sorts the in-memory coin list.
6. Renders `portfolio/templates/portfolio/overview.html`.

Concerns:

- External API failures, bad JSON, missing API fields, and rate limits are not handled in the view or service.
- Any invalid ledger state that breaks FIFO calculation causes a 500.
- No pagination or lazy loading for large portfolios.
- Template sort links pass an undefined `search` variable. It resolves falsy in Django templates, but it is dead context.
- The "Edit" action in the overview points to the add/create transaction page for a coin. A label like "Transactions" or "Manage" would better match the destination.

### `show_all_transactions`

Defined in `portfolio/views.py`.

Workflow:

1. Requires login.
2. Validates `page`, `sort`, and `direction`.
3. Loads user transactions via `PortfolioTransaction.get_for_user()`.
4. Uses `len(transactions)` for page clamping.
5. Orders, paginates, and renders `portfolio/templates/portfolio/all_transactions.html`.

Concerns:

- `len(transactions)` evaluates the queryset and loads all matching rows just to compute page count. Use `.count()` or let `Paginator` drive counts.
- Sorting by `total` depends on the annotation from `get_for_user()`.
- Inactive coins are filtered out, so all-transactions is not really all historical transactions.
- Deleting from page 2 redirects back to `/portfolio/all/` without preserving the query string because the hidden `next` uses `request.path`, not `request.get_full_path`.

### `create_portfolio_transaction`

Defined in `portfolio/views.py`.

Workflow:

1. Requires login.
2. Accepts either `coin_id` or `cg_id`.
3. Finds an active coin.
4. Loads the user's existing transactions for that coin.
5. Paginates the coin-specific transaction table.
6. Gets current balance.
7. If `transaction_id` is provided, loads that transaction for editing.
8. On POST, validates the form, checks sell amount against balance, saves user/coin, and redirects back to the add page.
9. Renders `portfolio/templates/portfolio/create_transaction.html`.

Good:

- User and coin ownership are enforced in the transaction queryset.
- Coin lookup is restricted to active coins.
- The form does not trust posted user or coin ids.

Concerns:

- First transaction can be a sell; `balance` is `None`, so `amount > balance` raises `TypeError`.
- Sell validation is not edit-aware and can reject valid sell edits.
- Buy edits are not checked against later sells and can create invalid ledgers.
- Negative or zero amounts/prices are accepted.
- The whole validation/save flow is not wrapped in a transaction or locked, so concurrent sell requests can oversell.
- Redirects after save discard current page/sort state.
- Invalid coins or transactions redirect to `coins:watchlist`, which is a coarse fallback and can hide the real problem from the user.

### `delete_portfolio_transaction`

Defined in `portfolio/views.py`.

Workflow:

1. Requires login and POST.
2. Loads active coin and transaction for the current user.
3. Checks whether deleting a buy would make final balance negative.
4. Deletes if allowed.
5. Redirects to posted `next` if present, otherwise the add page.

Concerns:

- Error message says "If you delete this sell transaction..." while the guarded case is deleting a buy.
- The check only protects final balance. It does not validate chronological FIFO feasibility after deletion.
- Posted `next` is trusted directly, creating an open redirect risk for crafted POSTs.
- No confirmation UI is present in the template.
- Invalid delete falls through to a redirect that may cause an extra hop through the add view.

### Templates

`portfolio/templates/portfolio/overview.html`:

- Shows summary metrics, "See all transactions", and a holdings table.
- Uses `common_extras` formatting and sort links.
- Shows empty state "No coins in your portfolio yet."

`portfolio/templates/portfolio/create_transaction.html`:

- Renders a crispy form for create/edit.
- Shows available balance via `{{ balance|floatformat }}`.
- Includes the coin-specific transaction table and pagination.

`portfolio/templates/portfolio/all_transactions.html`:

- Includes the shared transaction table with `show_coin_name=True`.
- Includes shared pagination.

`portfolio/templates/portfolio/partials/transactions_table.html`:

- Displays type, optional coin name, amount, price, total, date, edit/delete actions.
- Uses the annotated `tx.total` value.

Template concerns:

- `floatformat` without precision can hide crypto precision in balances.
- Tables are Bootstrap-default and may be cramped on mobile.
- Transaction row numbers reset per page.
- Delete buttons have no confirmation and look like text links.
- Empty transaction table text is always "Your portfolio is empty.", even on a coin detail page where "No transactions for this coin" would be clearer.
- The shared pagination partial always includes "Back to Market", which may not be the right back action from all portfolio contexts.

## Integration With Coins And Common Utilities

Coins integration:

- `portfolio.models.PortfolioTransaction.coin` references `coins.models.Coin`.
- Portfolio only considers `Coin.is_active=True` transactions through model helpers and views.
- Market rows link to the portfolio add view by CoinGecko id in `coins/templates/coins/partials/coins_table.html`.
- Overview market prices come from `coins.services.get_coin_list_with_market()`.
- `coins.services.get_coin_list_with_market()` does not cache calls with explicit ids, so portfolio overview requests can create repeated API traffic.
- `crypto_track/settings.py` requires `CRYPTO_COINGECKO_KEY` at import time, which affects tests, management commands, and any environment that does not have that variable.

Common utility integration:

- `common.decorators.views.validate_common_params()` protects sort/page query parameters and redirects invalid requests to the path without query string.
- `common.utils.get_common_params()` extracts page/sort/direction defaults after validation.
- `common.utils.add_direction_sign()` builds `order_by` direction strings.
- `common.templatetags.common_extras` supplies number, amount, percentage, class, and sort-link helpers.
- `common/templates/common/partials/pagination.html` is reused by portfolio pages.

These shared helpers are useful, but portfolio depends on conventions that are implicit: every sortable field must be whitelisted, every view must apply the decorator before calling `get_common_params()`, and pagination links only preserve the fields the partial knows about.

## Tests

Tests live in `portfolio/tests.py`.

Coverage present:

- `PortfolioTransaction.get_for_user()`.
- `PortfolioTransaction.get_coin_balance()` for one buy and one sell.
- `PortfolioTransaction.get_positive_coin_balance_ids()` for positive and zero balance.
- Authenticated portfolio overview renders expected context.
- Unauthenticated overview redirects to login.
- Empty overview shows an empty-state message.
- Overview sorting by allocation percentage.

Coverage gaps:

- No tests for `PortfolioTransactionForm`.
- No tests for creating transactions, invalid form input, first sell, oversell, editing, deleting, or all-transactions pagination/sorting.
- No tests for inactive coins and whether historical transactions should remain visible.
- No tests for `portfolio.services.build_holdings()` FIFO behavior.
- No tests for realized gain/loss expectations or cost basis naming.
- No tests for CoinGecko failures or missing market data.
- No tests for admin configuration.
- Existing overview tests appear to depend on the real `coins.services.get_coin_list_with_market()` path instead of mocking market data.

Test run attempted:

```bash
CRYPTO_COINGECKO_KEY=dummy python manage.py test portfolio --verbosity=2
```

Result in this environment: not executed because Django is not installed in the active Python environment (`ModuleNotFoundError: No module named 'django'`).

## Risks, Bugs, And Technical Debt

High priority:

- Invalid first sell can crash because `get_coin_balance()` returns `None`.
- Negative and zero amounts/prices are accepted through the form/model.
- Edit/delete validation can create invalid historical ledgers that break FIFO overview calculation.
- `build_holdings()` can crash on oversold history.
- Portfolio overview depends on live CoinGecko calls and has no error handling.
- Concurrent sell submissions can oversell because validation is not atomic.
- Tests are not isolated from external market data.

Medium priority:

- Inactive coins disappear from transaction history and balances.
- Admin form configuration likely needs `readonly_fields` for `created`.
- `show_all_transactions()` uses `len(queryset)` for pagination count.
- Delete `next` is trusted directly and can be an open redirect.
- Overview row `value` means cost basis, not current value, which is confusing.
- FIFO ordering should include a deterministic tiebreaker and probably a user-entered trade timestamp.
- No model indexes for expected user/coin/date queries.
- `CRYPTO_COINGECKO_KEY` is required at settings import time.

Lower priority and polish:

- Inconsistent trailing slashes in portfolio URLs.
- Empty `portfolio/utils.py`.
- Bootstrap-default tables and controls need mobile and UX polish.
- Delete action needs confirmation and clearer styling.
- Overview "Edit" label should better describe managing transactions.
- Balance display should preserve crypto precision.
- Pagination/back links should preserve context.

## Concrete Refactor And Polish Opportunities

1. Move ledger rules into the domain layer.
   - Add model/form validators for positive amount and positive price.
   - Centralize transaction create/edit/delete validation in a service instead of scattering checks through views.
   - Make validation transaction-aware for edits and deletes.
   - Return `Decimal("0")` from balance helpers when no rows exist.

2. Make transaction history robust.
   - Add indexes for `(user, coin, created)` and `(user, created)`.
   - Add a user-entered trade timestamp separate from `created`.
   - Use deterministic FIFO ordering such as `(trade_timestamp, id)`.
   - Decide whether coin deletion should be `PROTECT`, `SET_NULL`, or keep cascade.
   - Decide how inactive/delisted coins should appear in history and overview.

3. Isolate market data from portfolio logic.
   - Wrap CoinGecko calls behind a portfolio-facing market data interface.
   - Handle failures and missing prices explicitly.
   - Cache current market data for portfolio holdings or reuse a central price cache.
   - Convert API numeric values with `Decimal(str(value))` and handle `None`.

4. Clarify portfolio metrics.
   - Rename row `value` to `cost_basis`.
   - Add `market_value` per holding.
   - Keep `total_invested`, `portfolio_value`, and UPL naming consistent in services and templates.
   - Consider realized gain/loss if sell transactions are part of core tracking.
   - Consider fees, notes, exchange, currency, and import/export needs.

5. Improve views and URLs.
   - Split create and edit flows if they continue to diverge.
   - Preserve query string on redirects where useful.
   - Validate `next` redirects with allowed-host checks.
   - Normalize trailing slashes and path converters.
   - Use `.count()` or paginator metadata instead of `len(queryset)`.

6. Improve admin.
   - Add `readonly_fields = ("created",)` if showing timestamps.
   - Decide if transactions are immutable audit records or editable admin records.
   - Add admin tests or at least smoke coverage for add/view pages.

7. Expand tests before refactoring behavior.
   - Unit-test FIFO lot building with partial sells, full sells, multiple coins, and oversells.
   - Unit-test portfolio metrics with mocked market data.
   - Test create/edit/delete workflows, including invalid sell amounts and invalid edits.
   - Mock `coins.services.get_coin_list_with_market()` in portfolio view tests.
   - Add regression tests for inactive coins, empty balances, and external API failure states.

8. Polish UI.
   - Replace generic crispy defaults with clearer labels, min/step attributes, and precise decimal display.
   - Add delete confirmation.
   - Improve empty states per context.
   - Make tables responsive and preserve page/sort state after actions.
   - Use clearer action names: "Manage", "Add transaction", "Edit transaction", "Delete".

## Suggested Refactor Kickoff Order

1. Add tests around current intended ledger behavior with market data mocked.
2. Fix balance helpers to return zero and reject invalid decimal inputs.
3. Extract create/edit/delete validation into a portfolio service.
4. Harden `build_holdings()` and overview market-data error handling.
5. Rename metric fields internally for clarity, then update templates.
6. Add indexes/constraints/migrations once domain rules are agreed.
7. Polish UI and admin after behavior is stable.
