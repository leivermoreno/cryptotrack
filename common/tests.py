"""Direct tests for the shared ``common`` query/presentation helpers.

Subtask 2.3 of ``inspection/refactor_steps.md`` -- Section 2 SAFETY-NET
BASELINE. Two kinds of tests live here:

* GREEN characterization tests assert the CURRENT correct behavior so a future
  refactor cannot silently regress it.
* ``@unittest.expectedFailure`` tests assert the CORRECT (desired) behavior for
  a KNOWN BUG. They keep the suite green today (expected failures do not fail
  the run) and will flip to XPASS when the cited refactor step fixes the bug.

Bugs are catalogued in ``inspection/common.md`` ("High-value bugs" / the
per-file "Risks and bugs" sections). Each ``expectedFailure`` cites both the
inspection finding and the refactor step that will fix it.
"""

import unittest
from decimal import Decimal

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.utils.html import escape

from common.decorators.views import validate_common_params
from common.templatetags.common_extras import (
    format_amount,
    format_number,
    format_percentage,
    percentage_change_class,
    sort_link,
)
from common.utils import add_direction_sign, get_common_params

# The coins app's real ALLOWED_SORTS keys, used to drive the decorator tests.
ALLOWED_SORTS = {
    "rank": "market_cap_rank",
    "coin": "name",
    "price": "current_price",
}


# ---------------------------------------------------------------------------
# A) Formatting filters (common/templatetags/common_extras.py)
# ---------------------------------------------------------------------------
class FormatNumberTests(SimpleTestCase):
    """Characterize common_extras.format_number."""

    def test_none_returns_dash(self):
        self.assertEqual(format_number(None), "-")

    def test_integer_value_uses_thousands_separator(self):
        self.assertEqual(format_number(1234567), "1,234,567")

    def test_positive_value_ge_one_with_decimals_two_dp(self):
        self.assertEqual(format_number(1234.5), "1,234.50")

    def test_positive_decimal_value_ge_one_two_dp(self):
        # Decimal is the type portfolio values arrive as; >=1 path is correct.
        self.assertEqual(format_number(Decimal("1234.5")), "1,234.50")

    def test_small_positive_fraction_up_to_four_significant_digits(self):
        self.assertEqual(format_number(0.00012345), "0.0001234")

    def test_small_positive_half_value(self):
        self.assertEqual(format_number(0.5), "0.5")

    def test_small_negative_half_value(self):
        # -0.5 goes through the <1 branch and is formatted correctly today.
        self.assertEqual(format_number(-0.5), "-0.5")

    # --- KNOWN BUGS: negative non-integer formatting -----------------------
    # inspection/common.md, "High-value bugs" #1 + format_number/
    # get_decimal_formatted notes: get_decimal_formatted counts the leading
    # "-" as a significant character, and the ``value >= 1`` two-decimal branch
    # is skipped for negatives, so negative non-integers are truncated.
    # Fix: refactor step 8.1 (handle sign separately from significant digits).

    @unittest.expectedFailure
    def test_negative_value_ge_one_magnitude_two_dp(self):
        # Correct: "-12.34". Currently observed: "-12." (truncated). Step 8.1.
        self.assertEqual(format_number(-12.34), "-12.34")

    @unittest.expectedFailure
    def test_negative_small_value_two_dp(self):
        # Correct: "-1.23". Currently observed: "-1.2". Step 8.1.
        self.assertEqual(format_number(-1.23), "-1.23")

    @unittest.expectedFailure
    def test_negative_decimal_value_ge_one_magnitude(self):
        # Correct: "-12.34". Currently observed: "-12.". Step 8.1.
        self.assertEqual(format_number(Decimal("-12.34")), "-12.34")

    # --- KNOWN BUG: invalid/blank string input raises ----------------------
    # inspection/common.md, "High-value bugs" #1 (format_number assumes
    # int(value) succeeds). A blank/invalid string raises ValueError via
    # int(value) instead of rendering a safe fallback.
    # Fix: refactor step 8.2. The exact fallback string is finalized in 8.2;
    # "-" (matching the None case) is asserted here as the expected safe value.
    @unittest.expectedFailure
    def test_empty_string_returns_safe_fallback(self):
        # Correct: a safe fallback (asserting "-"). Currently raises ValueError.
        self.assertEqual(format_number(""), "-")


class FormatAmountTests(SimpleTestCase):
    """Characterize common_extras.format_amount."""

    def test_none_passes_through_dash(self):
        self.assertEqual(format_amount(None), "-")

    def test_positive_value_gets_dollar_prefix(self):
        self.assertEqual(format_amount(1234.5), "$1,234.50")

    # KNOWN BUG: inherits the negative-formatting defect from format_number.
    # inspection/common.md "High-value bugs" #1. Fix: refactor step 8.1.
    @unittest.expectedFailure
    def test_negative_value_gets_dollar_prefix(self):
        # Correct: "$-12.34". Currently observed: "$-12.". Step 8.1.
        self.assertEqual(format_amount(-12.34), "$-12.34")


class FormatPercentageTests(SimpleTestCase):
    """Characterize common_extras.format_percentage."""

    def test_none_returns_dash(self):
        self.assertEqual(format_percentage(None), "-")

    def test_exact_zero_normalized_to_zero(self):
        # "0.00" is normalized to "0" before appending "%".
        self.assertEqual(format_percentage(0), "0%")

    def test_positive_value_two_dp(self):
        self.assertEqual(format_percentage(1.5), "1.50%")

    # KNOWN BUG: tiny negatives render "-0.00%" because only exact "0.00" is
    # normalized to "0". inspection/common.md, format_percentage notes.
    # Fix: refactor step 8.3.
    @unittest.expectedFailure
    def test_tiny_negative_normalized_to_zero(self):
        # Correct: "0%". Currently observed: "-0.00%". Step 8.3.
        self.assertEqual(format_percentage(-0.001), "0%")

    @unittest.expectedFailure
    def test_tiny_negative_decimal_normalized_to_zero(self):
        # Correct: "0%". Currently observed: "-0.00%". Step 8.3.
        self.assertEqual(format_percentage(Decimal("-0.001")), "0%")


class PercentageChangeClassTests(SimpleTestCase):
    """Characterize common_extras.percentage_change_class."""

    def test_positive_is_success(self):
        self.assertEqual(percentage_change_class(1), "text-success")

    def test_negative_is_danger(self):
        self.assertEqual(percentage_change_class(-1), "text-danger")

    def test_none_returns_empty(self):
        self.assertEqual(percentage_change_class(None), "")

    def test_zero_is_currently_danger(self):
        # UNDECIDED DESIGN DECISION (refactor step 8.4): zero currently maps to
        # "text-danger" (value <= 0). Most financial UIs treat a 0% change as
        # neutral. This is characterized GREEN as the CURRENT behavior; step 8.4
        # will decide whether zero should become neutral. NOT an expectedFailure
        # because no decision has been made yet.
        self.assertEqual(percentage_change_class(0), "text-danger")


class AddDirectionSignTests(SimpleTestCase):
    """Characterize common.utils.add_direction_sign."""

    def test_asc_returns_plain_sort(self):
        self.assertEqual(add_direction_sign("rank", "asc"), "rank")

    def test_desc_returns_prefixed_sort(self):
        self.assertEqual(add_direction_sign("rank", "desc"), "-rank")


# ---------------------------------------------------------------------------
# B) validate_common_params decorator (common/decorators/views.py)
# ---------------------------------------------------------------------------
class ValidateCommonParamsTests(SimpleTestCase):
    """Characterize the validate_common_params redirect/pass behavior."""

    def setUp(self):
        self.rf = RequestFactory()

        @validate_common_params(ALLOWED_SORTS)
        def view(request):
            return HttpResponse("ok")

        self.view = view

    def _call(self, query=""):
        request = self.rf.get("/coins/" + query)
        return self.view(request)

    def test_no_params_runs(self):
        resp = self._call("")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"ok")

    def test_valid_sort_and_direction_runs(self):
        resp = self._call("?sort=rank&direction=asc")
        self.assertEqual(resp.status_code, 200)

    def test_page_zero_redirects(self):
        resp = self._call("?page=0")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/coins/")

    def test_page_negative_redirects(self):
        resp = self._call("?page=-1")
        self.assertEqual(resp.status_code, 302)

    def test_page_non_integer_redirects(self):
        resp = self._call("?page=abc")
        self.assertEqual(resp.status_code, 302)

    def test_unknown_sort_redirects(self):
        resp = self._call("?sort=nope&direction=asc")
        self.assertEqual(resp.status_code, 302)

    def test_invalid_direction_redirects(self):
        resp = self._call("?sort=rank&direction=up")
        self.assertEqual(resp.status_code, 302)

    def test_partial_pair_sort_only_redirects(self):
        # CURRENT behavior: providing sort without direction (or vice versa)
        # redirects, because the decorator requires both when either is present.
        # Refactor step 7 may relax this to allow a lone sort/direction.
        resp = self._call("?sort=rank")
        self.assertEqual(resp.status_code, 302)

    def test_trailing_whitespace_sort_does_not_redirect(self):
        # CURRENT behavior: the decorator .strip()s sort/direction for
        # validation, so "rank " validates as "rank" and the view runs.
        # BUT the whitespace is NOT stripped downstream: get_common_params
        # returns the raw "rank " (see GetCommonParamsTests below). The real
        # defect is the decorator/parser disagreement -- inspection/common.md
        # "High-value bugs" #3 (step 7.2). It cannot be cleanly asserted at the
        # decorator level alone; the passthrough test in C documents the raw
        # value that leaks through.
        resp = self._call("?sort=rank%20&direction=asc")
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# C) get_common_params reader closure (common/utils.py)
# ---------------------------------------------------------------------------
class GetCommonParamsTests(SimpleTestCase):
    """Characterize the get_common_params reader closure."""

    def setUp(self):
        self.rf = RequestFactory()
        self.read = get_common_params(default_sort="rank", default_direction="asc")

    def _read(self, query="", page_count=1):
        request = self.rf.get("/coins/" + query)
        return self.read(request, page_count)

    def test_defaults_when_params_absent(self):
        self.assertEqual(self._read("", page_count=3), (1, "rank", "asc"))

    def test_page_clamped_to_page_count(self):
        self.assertEqual(self._read("?page=99", page_count=3), (3, "rank", "asc"))

    def test_zero_page_count_treated_as_one(self):
        # page_count = page_count or 1 -> an empty result set is one page, so
        # any requested page clamps to 1.
        self.assertEqual(self._read("?page=5", page_count=0), (1, "rank", "asc"))

    def test_valid_sort_direction_passthrough(self):
        self.assertEqual(
            self._read("?page=2&sort=coin&direction=desc", page_count=5),
            (2, "coin", "desc"),
        )

    def test_non_integer_page_raises_without_decorator(self):
        # CHARACTERIZED GREEN (not expectedFailure): get_common_params does not
        # catch ValueError from int(page). In production the validate_common_params
        # decorator guards this (rejects non-int pages before the reader runs),
        # so this is guarded-by-decorator design debt rather than a user-facing
        # bug. Refactor step 7.2 centralizes normalization; this test pins the
        # current unguarded contract so that change is deliberate.
        with self.assertRaises(ValueError):
            self._read("?page=abc", page_count=3)

    def test_whitespace_sort_not_stripped_downstream(self):
        # Documents inspection/common.md "High-value bugs" #3: the decorator
        # strips "rank " to validate, but the reader returns it RAW. Step 7.2.
        self.assertEqual(
            self._read("?sort=rank%20&direction=asc", page_count=3),
            (1, "rank ", "asc"),
        )


# ---------------------------------------------------------------------------
# D) sort_link simple tag (common/templatetags/common_extras.py)
# ---------------------------------------------------------------------------
class SortLinkTests(SimpleTestCase):
    """Characterize the sort_link table-header link builder."""

    def test_current_sort_flips_direction_and_shows_up_arrow(self):
        html = str(sort_link("rank", 1, "rank", "asc", "", "Rank"))
        self.assertIn("direction=desc", html)
        # Up arrow entity for the ascending->toggle state.
        self.assertIn("&#8593;", html)

    def test_current_sort_desc_shows_down_arrow(self):
        html = str(sort_link("rank", 1, "rank", "desc", "", "Rank"))
        self.assertIn("&#8595;", html)

    def test_non_current_sort_defaults_to_asc(self):
        html = str(sort_link("rank", 2, "coin", "asc", "", "Rank"))
        self.assertIn("direction=asc", html)

    def test_href_contains_expected_query_keys(self):
        html = str(sort_link("rank", 2, "coin", "asc", "btc", "Rank"))
        self.assertIn("page=2", html)
        self.assertIn("sort=rank", html)
        self.assertIn("direction=", html)
        # search key is emitted when a search term is supplied (HTML-escaped &).
        self.assertIn("search=btc", html)

    def test_no_search_omits_search_param(self):
        html = str(sort_link("rank", 1, "coin", "asc", "", "Rank"))
        self.assertNotIn("search=", html)

    # KNOWN BUG: sort_link does not URL-encode the search value; it interpolates
    # the raw string (only HTML-escaped by format_html). A search term with
    # spaces / reserved chars produces a broken query string.
    # inspection/common.md "High-value bugs" #4. Fix: refactor step 7.3/7.4.
    # The assertion focuses on URL-encoding of the query value (not HTML
    # escaping): after the fix the value should appear percent-encoded.
    @unittest.expectedFailure
    def test_search_value_is_url_encoded(self):
        html = str(sort_link("rank", 1, "coin", "asc", "a b&c=d", "Rank"))
        # Correct: percent-encoded (quote: "a%20b%26c%3Dd" or quote_plus:
        # "a+b%26c%3Dd"). Currently the raw "a b&c=d" is interpolated (with the
        # "&" merely HTML-escaped to "&amp;"), so no percent-encoding appears.
        self.assertTrue(
            ("a%20b%26c%3Dd" in html) or ("a+b%26c%3Dd" in html),
            msg=f"search value not URL-encoded in href: {html!r}",
        )


# ---------------------------------------------------------------------------
# E) Pagination partial (common/templates/common/partials/pagination.html)
# ---------------------------------------------------------------------------
class PaginationPartialTests(SimpleTestCase):
    """Characterize the shared pagination partial rendering."""

    def setUp(self):
        self.rf = RequestFactory()
        self.paginator = Paginator(list(range(25)), 10)  # 3 pages

    def _render(self, page_number):
        request = self.rf.get("/coins/search/")
        return render_to_string(
            "common/partials/pagination.html",
            {
                "page_obj": self.paginator.page(page_number),
                "sort": "rank",
                "direction": "asc",
                "send_search": True,
                "search_query": "btc",
            },
            request=request,
        )

    def test_first_page_has_next_only(self):
        html = self._render(1)
        self.assertIn(">next</a>", html)
        self.assertNotIn(">previous</a>", html)
        self.assertIn("page=2", html)

    def test_middle_page_has_previous_and_next(self):
        html = self._render(2)
        self.assertIn(">previous</a>", html)
        self.assertIn(">next</a>", html)

    def test_last_page_has_previous_only(self):
        html = self._render(3)
        self.assertIn(">previous</a>", html)
        self.assertNotIn(">next</a>", html)

    def test_links_use_request_path_and_preserve_sort_direction_search(self):
        html = self._render(2)
        self.assertIn("/coins/search/?page=1", html)
        self.assertIn("sort=rank", html)
        self.assertIn("direction=asc", html)
        self.assertIn("search=btc", html)

    def test_always_renders_hardcoded_back_to_market_link(self):
        # CURRENT behavior: the "common" partial hard-codes a "Back to Market"
        # button pointing at coins:index (resolves to "/"), so every consumer
        # (incl. portfolio transaction pages) inherits it. Refactor step 7.6
        # will make the back-link generic/optional. Characterized GREEN.
        html = self._render(1)
        self.assertIn("Back to Market", html)
        self.assertIn('href="/"', html)

    def test_search_query_not_url_encoded_in_partial(self):
        # Companion to the sort_link bug: the partial also concatenates
        # search_query without URL-encoding (inspection/common.md
        # "High-value bugs" #4). This is a render-level characterization of the
        # CURRENT behavior -- a plain term ("btc") is emitted verbatim. NOT an
        # expectedFailure here: the reusable-partial/encoding fix is tracked at
        # the tag level (SortLinkTests) and refactor step 7.3/7.4/7.6; this
        # simply documents that the partial performs no encoding today.
        request = self.rf.get("/coins/search/")
        html = render_to_string(
            "common/partials/pagination.html",
            {
                "page_obj": self.paginator.page(1),
                "sort": "rank",
                "direction": "asc",
                "send_search": True,
                "search_query": "a b",
            },
            request=request,
        )
        # Django auto-escapes HTML but does not URL-encode: the raw space
        # survives (would be "%20" or "+" if encoded).
        self.assertIn("search=" + escape("a b"), html)
        self.assertNotIn("search=a%20b", html)

    @unittest.expectedFailure
    def test_search_query_should_be_url_encoded_in_partial(self):
        # Desired-behavior companion to the green characterization above. The
        # tag-level fix is asserted by SortLinkTests.test_search_value_is_url_encoded,
        # but the partial template concatenates search_query into href directly
        # (pagination.html:5 and :11) with no encoding, so it needs its own
        # expected-failure so the reusable-partial/encoding fix (refactor step
        # 7.3/7.4/7.6) is not blocked by a green test freezing the bug.
        request = self.rf.get("/coins/search/")
        html = render_to_string(
            "common/partials/pagination.html",
            {
                "page_obj": self.paginator.page(1),
                "sort": "rank",
                "direction": "asc",
                "send_search": True,
                "search_query": "a b",
            },
            request=request,
        )
        # Correct: percent-encoded (quote: "a%20b" or quote_plus: "a+b").
        self.assertTrue(
            ("search=a%20b" in html) or ("search=a+b" in html),
            msg=f"search value not URL-encoded in partial href: {html!r}",
        )
