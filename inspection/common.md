# Common App Inspection

## Scope

Inspected the `common/` Django app and shared wiring files needed to understand it:

- `common/`
- `crypto_track/settings.py`
- `templates/base.html`
- `static/style.css`
- `requirements.txt`
- `README.md`
- Consumer call sites in `coins/` and `portfolio/` where they use common helpers

This is an inspection-only pass. No application code was modified.

## Executive Summary

`common` is not a domain/data app. It is a small shared UI/query-helper app that centralizes:

- query parameter validation for `page`, `sort`, and `direction`
- extraction/clamping of pagination and sorting params
- conversion from sort/direction into Django `order_by()` syntax
- table sorting links
- crypto/portfolio numeric formatting filters
- a reusable pagination partial

It is installed as `common.apps.CommonConfig` in `crypto_track/settings.py:47`, with app templates enabled by `APP_DIRS = True` in `crypto_track/settings.py:76`. The request context processor is enabled at `crypto_track/settings.py:79`, which the common pagination partial relies on for `request.path`.

The app works as glue for `coins` and `portfolio`, but it has several rough edges that should be addressed during a refactor:

- the "common" pagination partial is domain-specific and hard-codes a `coins:index` back link
- pagination and sort URL building is duplicated and does not URL-encode values
- the `get_common_params()` helper depends on a separate decorator for safety
- portfolio passes row counts where page counts are expected, which can raise `EmptyPage`
- number formatting has real bugs for negative non-integer values
- there are no direct tests for the common helpers, decorators, tags, or partial behavior

## Architecture and Wiring

### App registration

- `common/apps.py:4` defines `CommonConfig`.
- `crypto_track/settings.py:47` installs `"common.apps.CommonConfig"` before `coins`, `accounts`, and `portfolio`.
- `crypto_track/settings.py:72` to `crypto_track/settings.py:85` uses Django templates with `APP_DIRS = True`, so `common/templates/common/...` is discoverable.
- `templates/base.html:47` includes the global search form from `coins`, not from `common`; `common` is not involved in the base shell except through shared CSS/template availability.
- `static/style.css` is minimal global layout CSS only; no common-specific styling exists.
- `requirements.txt` pins Django `5.2.5`, Bootstrap is loaded from CDN in `templates/base.html`, and no frontend build system is present.

### URL and model ownership

- There is no `common/urls.py`.
- `common/models.py` is boilerplate only and defines no models.
- `common/migrations/__init__.py` exists, but there are no common migrations.
- `common/views.py` is boilerplate only and defines no views.
- `common/admin.py` is boilerplate only and registers nothing.

The app is therefore a utility/template app. Its public surface is imported by other apps rather than routed directly.

## File Inventory

### `common/utils.py`

Defines two helper factories/functions:

- `add_direction_sign(sort, direction)` at `common/utils.py:1`
  - Returns `"-{sort}"` when `direction == "desc"`, otherwise returns `sort`.
  - Used by portfolio queryset ordering.

- `get_common_params(default_sort, default_direction)` at `common/utils.py:7`
  - Returns a closure that reads `page`, `sort`, and `direction` from `request.GET`.
  - Converts `page` to `int`, defaults to `1`, clamps it to `page_count`, and falls back to provided default sort/direction.
  - The helper expects invalid values to have already been handled by `validate_common_params()`.

Important behavior:

- `page_count = page_count or 1` treats empty result sets as one page.
- It does not strip `sort` or `direction`, even though the decorator does during validation.
- It does not catch `ValueError` from `int()`. Calling it without the decorator can crash on invalid `page`.
- The `page_count` argument is a page count, not an item count. Some portfolio views currently pass item counts.

### `common/decorators/views.py`

Defines `validate_common_params(allowed_sorts)` at `common/decorators/views.py:6`.

Behavior:

- Assumes a function-based view and reads `request = args[0]` at `common/decorators/views.py:10`.
- Allows absent `page`, `sort`, and `direction`.
- Rejects `page` if it cannot be parsed as an integer or is less than `1`.
- If either `sort` or `direction` is present, requires both:
  - `sort in allowed_sorts`
  - `direction in ["asc", "desc"]`
- Redirects to `request.path` on invalid input, dropping all query parameters.

This decorator is the main safety boundary for common sorting. It accepts either a list of allowed sort names (`portfolio`) or a dictionary whose keys are allowed sort names (`coins`).

Risks:

- It strips values for validation but does not pass stripped values downstream. A URL like `?sort=rank%20&direction=asc` can validate as `rank` but still reach consumers as raw `rank `.
- Redirecting to `request.path` sanitizes aggressively but also drops legitimate state such as `search`.
- It only validates the presence/shape of query params. It does not know the real page count and does not clamp high page values.
- The `args[0]` request assumption is fine for current function views, but it is not reusable for class-based views or functions with a different signature.

### `common/templatetags/common_extras.py`

Defines all shared template filters/tags:

- `multiply` at `common/templatetags/common_extras.py:8`
- `get_decimal_formatted` helper at `common/templatetags/common_extras.py:16`
- `format_number` at `common/templatetags/common_extras.py:32`
- `format_amount` at `common/templatetags/common_extras.py:46`
- `format_percentage` at `common/templatetags/common_extras.py:55`
- `percentage_change_class` at `common/templatetags/common_extras.py:66`
- `sort_link` at `common/templatetags/common_extras.py:76`

What they do:

- `format_number` displays `None` as `-`, integers with thousands separators, values `>= 1` with two decimals, and small fractional values with up to four significant digits.
- `format_amount` prefixes formatted numbers with `$`.
- `format_percentage` formats with two decimals, converting exact `"0.00"` to `"0%"`.
- `percentage_change_class` returns Bootstrap color classes: `text-danger` for values `<= 0`, `text-success` for values `> 0`.
- `sort_link` builds a table-header link with `page`, `sort`, `direction`, optional `search`, and a visual arrow for current sort state.

Risks and bugs:

- `format_number()` mishandles negative non-integer values because `get_decimal_formatted()` treats `-` as the first significant character. Examples such as `-12.34`, `-1.23`, and `-0.5` can be truncated incorrectly.
- `format_number()` assumes the input can be converted with `int(value)` and formatted numerically. A blank string or unexpected string can raise instead of rendering a safe fallback.
- `multiply()` converts through `float`, which loses `Decimal` precision. It appears unused in the repo.
- `format_percentage()` can render `-0.00%` for tiny negative values because only `"0.00"` is normalized.
- `percentage_change_class()` marks zero as `text-danger`. That may be a product decision, but most financial UIs treat zero as neutral.
- `sort_link()` does HTML escaping through `format_html()`, which is good, but it does not URL-encode query values. Search terms containing spaces, `&`, `=`, `#`, or `?` can create broken or surprising links.
- `sort_link()` only preserves `search`; any future filters or query parameters will be dropped.
- `sort_link()` keeps the current page when changing sort. That can produce confusing results and can combine badly with high page numbers.
- `common/templatetags/` has no `__init__.py`. Modern Python namespace packages may still import, but an explicit file would match Django convention and reduce ambiguity.

### `common/templates/common/partials/pagination.html`

Defines a reusable pagination snippet.

Current contract:

- Expects `page_obj` with Django `Page` methods/properties.
- Expects `sort` and `direction`.
- Reads `request.path`, relying on `django.template.context_processors.request`.
- Optionally preserves `search_query` only when included with `send_search=True`.

Behavior:

- Always renders a "Back to Market" button to `{% url 'coins:index' %}`.
- Renders previous/next links when `page_obj.has_previous` or `page_obj.has_next`.
- Keeps current `sort` and `direction` in pagination URLs.

Risks:

- It is not truly common because it hard-codes `coins:index` and "Back to Market" in `common/templates/common/partials/pagination.html:2`.
- It manually concatenates query strings and does not URL-encode `search_query`.
- It does not preserve arbitrary query params.
- It has no disabled states, first/last links, total page display, or accessible labels.
- It assumes all consumers want a back-to-market action. Portfolio transaction screens currently inherit that unrelated action.

### Boilerplate files

- `common/models.py`, `common/views.py`, `common/admin.py`, and `common/tests.py` are still generated stubs.
- `common/decorators/__init__.py`, `common/__init__.py`, and `common/migrations/__init__.py` are empty package files.

These stubs are harmless, but they add noise in an app that is purely utilities/templates.

## Consumers

### Coins app

`coins/views.py` imports and instantiates common helpers:

- `validate_common_params` from `common.decorators.views`
- `get_common_params` from `common.utils`

At `coins/views.py:19` and `coins/views.py:20`, the imported names are reassigned:

- `validate_common_params = validate_common_params(ALLOWED_SORTS)`
- `get_common_params = get_common_params(default_sort="rank", default_direction="asc")`

That pattern works, but it shadows the factories and makes the module harder to read.

Usage by view:

- `render_index` uses the decorator, gets external CoinGecko page count, and passes `page_number`, `page_count`, `sort`, and `direction` into `coins/index.html`.
- `render_search` validates params, computes a page count from matching local `Coin` IDs, paginates IDs with Django `Paginator`, fetches market data for the current page, and includes `common/partials/pagination.html` with `send_search=True`.
- `render_watchlist` validates params, paginates a queryset/list of user CoinGecko IDs, fetches market data for the current page, and includes `common/partials/pagination.html`.

Templates:

- `coins/templates/coins/partials/coins_table.html` loads `common_extras` and uses `sort_link`, `format_amount`, `format_percentage`, and `percentage_change_class`.
- `coins/templates/coins/search.html` and `coins/templates/coins/watchlist.html` include `common/partials/pagination.html`.
- `coins/templates/coins/index.html` does not use the common pagination partial. It has its own pagination markup and drops `sort`/`direction` when moving pages, so sorting state is lost on the market index.

Important coupling:

- `coins/settings.py` defines `ALLOWED_SORTS` as a mapping from URL sort keys to CoinGecko response keys. The decorator validates membership against that mapping; `coins/services.py` later indexes the same mapping in `_sort_coin_list()`.

### Portfolio app

`portfolio/views.py` imports:

- `validate_common_params`
- `get_common_params`
- `add_direction_sign`

At `portfolio/views.py:21` and `portfolio/views.py:22`, it creates defaults for transaction list pages:

- allowed sorts from `portfolio/settings.py`
- default sort `created`
- default direction `desc`

Usage by view:

- `portfolio_overview` uses `@validate_common_params(OVERVIEW_ALLOWED_SORTS)`, but does not call `get_common_params()`. It reads raw `request.GET` values directly at `portfolio/views.py:40` and `portfolio/views.py:41`, then sorts an in-memory `coin_list`.
- `show_all_transactions` uses `get_common_params_defaults()` and `add_direction_sign()` before applying `.order_by()` to a transaction queryset.
- `create_portfolio_transaction` uses the same transaction-list pagination/sorting helpers for transactions belonging to a single coin.

Templates:

- `portfolio/templates/portfolio/overview.html` loads `common_extras` and uses `sort_link`, `format_amount`, `format_number`, `format_percentage`, and `percentage_change_class`.
- `portfolio/templates/portfolio/partials/transactions_table.html` loads `common_extras` and uses `sort_link`, `format_number`, and `format_amount`.
- `portfolio/templates/portfolio/all_transactions.html` and `portfolio/templates/portfolio/create_transaction.html` include `common/partials/pagination.html`.

Important bugs/coupling:

- `show_all_transactions` passes `page_count=len(transactions)` at `portfolio/views.py:63` to `portfolio/views.py:65`. That is item count, not page count. If a user requests a page number higher than the actual paginator page count but less than the item count, `Paginator(...).page(page)` can raise `EmptyPage`.
- `create_portfolio_transaction` has the same issue at `portfolio/views.py:92` to `portfolio/views.py:96`.
- Calling `len(transactions)` evaluates the queryset. It should use `Paginator.num_pages` or `QuerySet.count()` depending on the refactor direction.
- `portfolio_overview` validates stripped sort values but then reads raw GET values, so whitespace variants can still produce `KeyError`.
- Portfolio pages inherit the common pagination partial's "Back to Market" link, which is awkward on transaction workflows.

## Tests

`common/tests.py` is empty. There are no direct tests for:

- valid and invalid `validate_common_params()` inputs
- `get_common_params()` defaults, clamping, invalid page behavior, and empty page counts
- `add_direction_sign()`
- numeric formatting, especially decimals, zero, `None`, negative numbers, and invalid values
- `sort_link()` output and query encoding
- `common/partials/pagination.html` behavior

Existing app tests touch common behavior indirectly:

- `coins/tests.py` exercises index/search/watchlist view responses but does not assert sorting, pagination query preservation, or invalid param redirects.
- `portfolio/tests.py` has one overview sorting assertion but does not cover transaction-list sorting/pagination or common formatting.

I did not run the test suite during this inspection. The active Python environment in this workspace does not have Django installed (`ModuleNotFoundError: No module named 'django'`), so runtime verification was not available without environment setup.

## Risks, Bugs, and Technical Debt

### High-value bugs

1. Negative number formatting is broken for non-integer negative values.
   - Location: `common/templatetags/common_extras.py:16` and `common/templatetags/common_extras.py:32`
   - Impact: negative unrealized profit/loss and negative fractional values may render incorrectly.

2. Portfolio transaction pagination can raise `EmptyPage`.
   - Location: `portfolio/views.py:63` to `portfolio/views.py:67`, and `portfolio/views.py:92` to `portfolio/views.py:96`
   - Cause: common helper receives item count instead of real page count.
   - Impact: high `page` values can cause server errors instead of redirecting/clamping.

3. Decorator validation and downstream parsing disagree about stripped values.
   - Location: `common/decorators/views.py:12`, `common/decorators/views.py:13`, `common/utils.py:12`, `common/utils.py:13`
   - Impact: query params with surrounding whitespace can validate but still crash or behave incorrectly in consumers.

4. Query strings are manually built and not URL-encoded.
   - Location: `common/templatetags/common_extras.py:87` to `common/templatetags/common_extras.py:92`, `common/templates/common/partials/pagination.html`
   - Impact: search terms or future filters containing reserved URL characters can break navigation.

### Design debt

1. `common` mixes generic helpers with crypto-specific presentation.
   - `format_amount()` hard-codes dollars.
   - `pagination.html` hard-codes "Back to Market" and `coins:index`.

2. Pagination is inconsistent across screens.
   - Market index has custom pagination that drops sort state.
   - Search/watchlist/portfolio use the common partial.
   - Some views use external page numbers; others use Django `Page` objects; overview is unpaginated.

3. Sorting state is split across decorator, utility function, service mappings, template tags, and templates.
   - This makes it easy to validate one value and then use another.
   - It also makes "preserve params" behavior inconsistent.

4. Common files are partly generated stubs.
   - `models.py`, `views.py`, `admin.py`, and `tests.py` do not express the real app purpose.

5. Naming is generic to the point of hiding behavior.
   - `get_common_params()` actually means "build a request query parser for page/sort/direction".
   - `validate_common_params()` is specifically a page/sort/direction validator.
   - `sort_link()` is specifically a table-header link builder.

### Security and robustness notes

- `sort_link()` uses `format_html()`, so direct HTML injection risk is reduced.
- `mark_safe()` is only used for internally selected arrow entities, so it is low risk.
- The larger risk is URL/query manipulation, not HTML injection.
- `redirect(request.path)` strips bad query parameters and avoids redirecting to a user-supplied URL, which is safe but blunt.

## Refactor and Polish Opportunities

### Clarify app responsibility

- Decide whether `common` should remain a generic shared app or become a UI helper package.
- If it remains generic, remove crypto-specific assumptions from shared partials and tags.
- If it becomes presentation-focused, name and document it accordingly.

### Replace ad hoc query handling with a single query-state helper

Create one small object or function that:

- accepts a `request`
- knows allowed sort keys and defaults
- normalizes whitespace
- validates direction
- exposes sanitized `page`, `sort`, and `direction`
- can emit encoded query strings while preserving selected params

This would replace the current split between:

- `validate_common_params()`
- `get_common_params()`
- `sort_link()`
- manual query concatenation in templates

### Fix pagination contracts

- Make `get_common_params()` accept an actual `Paginator` or `Page` object instead of a loosely named `page_count`.
- Or rename `page_count` to `num_pages` and enforce it at call sites.
- Update portfolio transaction pages to use real `Paginator.num_pages`.
- Make index/search/watchlist/all-transactions pagination share one behavior for preserving sort and query params.

### Make pagination partial actually reusable

Replace hard-coded "Back to Market" with optional include parameters, for example:

- `back_url`
- `back_label`
- `show_back`
- `query_params`

Or move the back action out of pagination entirely and let each page own its navigation.

### Use URL encoding APIs

- Build query strings with Django/Python URL encoding rather than template string concatenation.
- Preserve only intentional params, but do so centrally.
- Encode `search_query` in both `sort_link()` and `pagination.html`.

### Fix number formatting

- Use `Decimal`-aware formatting for portfolio values.
- Handle sign separately from significant-digit formatting.
- Define expected behavior for:
  - `None`
  - `0`
  - tiny positive values
  - tiny negative values
  - negative dollar amounts
  - invalid/non-numeric inputs
- Consider neutral display for zero percentage changes.

### Improve template tag boundaries

- Keep formatting filters small and pure.
- Move link-building out of a simple tag if query state becomes more structured.
- Add `common/templatetags/__init__.py` for convention and clarity.
- Remove unused `multiply` if no future use is planned.

### Add focused tests

Suggested direct tests for `common`:

- `validate_common_params()` accepts empty params and valid pairs.
- It redirects invalid pages, negative pages, invalid sort, invalid direction, and partial sort/direction pairs.
- It handles whitespace consistently after the refactor.
- `get_common_params()` clamps page numbers to actual page counts.
- Portfolio pagination does not raise for high page values.
- `format_number()` and `format_amount()` cover positive, negative, integer, fractional, small decimal, zero, and `None`.
- `format_percentage()` covers zero, tiny positive, tiny negative, and `None`.
- `sort_link()` preserves and encodes search terms.
- The pagination partial renders correct links for first/middle/last pages and optional back-link behavior.

## Suggested Refactor Order

1. Add tests around current common helpers and the most important consumer flows.
2. Fix negative number formatting and URL encoding first because those are user-visible.
3. Fix portfolio paginator page-count usage.
4. Introduce a centralized normalized query-state helper.
5. Replace duplicated pagination/sort URL construction with that helper.
6. Split the hard-coded back-to-market button out of the common pagination partial.
7. Clean up unused generated stubs or add module docstrings that explain the app's purpose.

## Bottom Line

`common` is small but sits on a critical path for nearly every list/table view. It is worth refactoring early because it controls sort links, pagination continuity, and financial display formatting across the app. The highest-impact work is to make query state normalized and encoded in one place, fix Decimal/negative formatting, and make the pagination partial truly context-neutral.
