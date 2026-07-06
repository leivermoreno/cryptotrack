"""Direct tests for the shared ``common`` query/presentation helpers.

Subtask 2.3 of ``inspection/refactor_steps.md`` started these as safety-net
tests. Later refactor sections converted the known formatter bugs into
regression coverage while preserving characterization coverage for shared query
and presentation behavior.
"""

from decimal import Decimal
from html import unescape
from urllib.parse import parse_qs, urlsplit

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings

from common.decorators.views import validate_common_params
from common.templatetags.common_extras import (
    format_amount,
    format_number,
    format_percentage,
    pagination_query,
    percentage_change_class,
    sort_link,
)
from common.utils import (
    InvalidQueryState,
    QueryState,
    add_direction_sign,
    get_common_params,
    get_safe_redirect_url,
    normalize_query_state,
)

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

    def test_negative_value_ge_one_magnitude_two_dp(self):
        self.assertEqual(format_number(-12.34), "-12.34")

    def test_negative_small_value_two_dp(self):
        self.assertEqual(format_number(-1.23), "-1.23")

    def test_negative_decimal_value_ge_one_magnitude(self):
        self.assertEqual(format_number(Decimal("-12.34")), "-12.34")

    def test_empty_string_returns_safe_fallback(self):
        self.assertEqual(format_number(""), "-")

    def test_invalid_string_returns_safe_fallback(self):
        self.assertEqual(format_number("abc"), "-")

    def test_blank_string_returns_safe_fallback(self):
        self.assertEqual(format_number("   "), "-")

    def test_zero_returns_zero(self):
        self.assertEqual(format_number(0), "0")

    def test_tiny_negative_decimal_up_to_four_significant_digits(self):
        self.assertEqual(format_number(Decimal("-0.00012345")), "-0.0001234")

    def test_large_decimal_uses_thousands_separator(self):
        self.assertEqual(
            format_number(Decimal("999999999999.99")),
            "999,999,999,999.99",
        )


class FormatAmountTests(SimpleTestCase):
    """Characterize common_extras.format_amount."""

    def test_none_passes_through_dash(self):
        self.assertEqual(format_amount(None), "-")

    def test_positive_value_gets_dollar_prefix(self):
        self.assertEqual(format_amount(1234.5), "$1,234.50")

    def test_negative_value_gets_dollar_prefix(self):
        self.assertEqual(format_amount(-12.34), "$-12.34")

    def test_empty_string_passes_through_dash(self):
        self.assertEqual(format_amount(""), "-")

    def test_invalid_string_passes_through_dash(self):
        self.assertEqual(format_amount("abc"), "-")

    def test_zero_gets_dollar_prefix(self):
        self.assertEqual(format_amount(0), "$0")

    def test_tiny_negative_decimal_gets_dollar_prefix(self):
        self.assertEqual(format_amount(Decimal("-0.00012345")), "$-0.0001234")

    def test_large_decimal_gets_dollar_prefix(self):
        self.assertEqual(
            format_amount(Decimal("999999999999.99")),
            "$999,999,999,999.99",
        )


class FormatPercentageTests(SimpleTestCase):
    """Characterize common_extras.format_percentage."""

    def test_none_returns_dash(self):
        self.assertEqual(format_percentage(None), "-")

    def test_exact_zero_normalized_to_zero(self):
        # "0.00" is normalized to "0" before appending "%".
        self.assertEqual(format_percentage(0), "0%")

    def test_positive_value_two_dp(self):
        self.assertEqual(format_percentage(1.5), "1.50%")

    def test_empty_string_returns_dash(self):
        self.assertEqual(format_percentage(""), "-")

    def test_invalid_string_returns_dash(self):
        self.assertEqual(format_percentage("abc"), "-")

    def test_tiny_positive_decimal_normalized_to_zero(self):
        self.assertEqual(format_percentage(Decimal("0.001")), "0%")

    def test_large_decimal_keeps_two_dp(self):
        self.assertEqual(
            format_percentage(Decimal("999999999999.99")),
            "999999999999.99%",
        )

    def test_tiny_negative_normalized_to_zero(self):
        self.assertEqual(format_percentage(-0.001), "0%")

    def test_tiny_negative_decimal_normalized_to_zero(self):
        self.assertEqual(format_percentage(Decimal("-0.001")), "0%")

    def test_negative_value_that_does_not_round_to_zero_keeps_sign(self):
        self.assertEqual(format_percentage(Decimal("-0.01")), "-0.01%")


class PercentageChangeClassTests(SimpleTestCase):
    """Characterize common_extras.percentage_change_class."""

    def test_positive_is_success(self):
        self.assertEqual(percentage_change_class(1), "text-success")

    def test_negative_is_danger(self):
        self.assertEqual(percentage_change_class(-1), "text-danger")

    def test_none_returns_empty(self):
        self.assertEqual(percentage_change_class(None), "")

    def test_zero_is_neutral(self):
        self.assertEqual(percentage_change_class(0), "")

    def test_tiny_positive_displayed_as_zero_is_neutral(self):
        self.assertEqual(percentage_change_class(Decimal("0.001")), "")

    def test_tiny_negative_displayed_as_zero_is_neutral(self):
        self.assertEqual(percentage_change_class(Decimal("-0.001")), "")

    def test_negative_value_that_does_not_round_to_zero_is_danger(self):
        self.assertEqual(percentage_change_class(Decimal("-0.01")), "text-danger")

    def test_invalid_string_returns_empty(self):
        self.assertEqual(percentage_change_class("abc"), "")


class AddDirectionSignTests(SimpleTestCase):
    """Characterize common.utils.add_direction_sign."""

    def test_asc_returns_plain_sort(self):
        self.assertEqual(add_direction_sign("rank", "asc"), "rank")

    def test_desc_returns_prefixed_sort(self):
        self.assertEqual(add_direction_sign("rank", "desc"), "-rank")


@override_settings(ALLOWED_HOSTS=["testserver"])
class GetSafeRedirectUrlTests(SimpleTestCase):
    """Validate the shared redirect target helper."""

    def setUp(self):
        self.rf = RequestFactory()

    def _request(self, secure=False):
        return self.rf.get("/coins/", secure=secure)

    def test_valid_relative_path_with_query_string_is_returned(self):
        redirect_to = "/coins/watchlist/?page=2&sort=price&direction=desc"
        self.assertEqual(
            get_safe_redirect_url(self._request(), redirect_to),
            redirect_to,
        )

    def test_valid_same_host_absolute_url_is_returned(self):
        redirect_to = "http://testserver/coins/watchlist/?page=2"
        self.assertEqual(
            get_safe_redirect_url(self._request(), redirect_to),
            redirect_to,
        )

    def test_none_is_rejected(self):
        self.assertIsNone(get_safe_redirect_url(self._request(), None))

    def test_blank_string_is_rejected(self):
        self.assertIsNone(get_safe_redirect_url(self._request(), "   "))

    def test_safe_string_is_stripped_before_return(self):
        self.assertEqual(
            get_safe_redirect_url(self._request(), "  /coins/watchlist/  "),
            "/coins/watchlist/",
        )

    def test_external_url_is_rejected(self):
        self.assertIsNone(
            get_safe_redirect_url(self._request(), "https://evil.example/")
        )

    def test_protocol_relative_url_is_rejected(self):
        self.assertIsNone(get_safe_redirect_url(self._request(), "//evil.example/"))

    def test_malformed_backslash_url_is_rejected(self):
        self.assertIsNone(
            get_safe_redirect_url(
                self._request(),
                r"https:\evil.example\phishing",
            )
        )

    def test_secure_request_rejects_same_host_http_url(self):
        self.assertIsNone(
            get_safe_redirect_url(
                self._request(secure=True),
                "http://testserver/coins/watchlist/",
            )
        )


# ---------------------------------------------------------------------------
# B) normalize_query_state helper (common/utils.py)
# ---------------------------------------------------------------------------
class NormalizeQueryStateTests(SimpleTestCase):
    """Validate the intended page/sort/direction normalization API."""

    def setUp(self):
        self.rf = RequestFactory()

    def _state(self, query="", page_count=None):
        request = self.rf.get("/coins/" + query)
        return normalize_query_state(
            request,
            allowed_sorts=ALLOWED_SORTS,
            default_sort="rank",
            default_direction="asc",
            page_count=page_count,
        )

    def test_defaults_when_params_absent(self):
        self.assertEqual(
            self._state("", page_count=3),
            QueryState(page=1, sort="rank", direction="asc"),
        )

    def test_page_clamped_to_page_count(self):
        self.assertEqual(
            self._state("?page=99", page_count=3),
            QueryState(page=3, sort="rank", direction="asc"),
        )

    def test_zero_page_count_treated_as_one(self):
        self.assertEqual(
            self._state("?page=5", page_count=0),
            QueryState(page=1, sort="rank", direction="asc"),
        )

    def test_valid_sort_direction_passthrough(self):
        self.assertEqual(
            self._state("?page=2&sort=coin&direction=desc", page_count=5),
            QueryState(page=2, sort="coin", direction="desc"),
        )

    def test_whitespace_is_stripped_before_use(self):
        self.assertEqual(
            self._state("?page=%202%20&sort=%20rank%20&direction=%20asc%20"),
            QueryState(page=2, sort="rank", direction="asc"),
        )

    def test_blank_values_use_defaults(self):
        self.assertEqual(
            self._state("?page=&sort=&direction=", page_count=3),
            QueryState(page=1, sort="rank", direction="asc"),
        )

    def test_non_integer_page_is_invalid(self):
        with self.assertRaises(InvalidQueryState):
            self._state("?page=abc", page_count=3)

    def test_page_less_than_one_is_invalid(self):
        with self.assertRaises(InvalidQueryState):
            self._state("?page=0", page_count=3)

    def test_unknown_sort_is_invalid(self):
        with self.assertRaises(InvalidQueryState):
            self._state("?sort=nope&direction=asc")

    def test_invalid_direction_is_invalid(self):
        with self.assertRaises(InvalidQueryState):
            self._state("?sort=rank&direction=up")

    def test_partial_sort_direction_pair_is_invalid(self):
        with self.assertRaises(InvalidQueryState):
            self._state("?sort=rank")


# ---------------------------------------------------------------------------
# C) validate_common_params compatibility decorator (common/decorators/views.py)
# ---------------------------------------------------------------------------
class ValidateCommonParamsTests(SimpleTestCase):
    """Validate the compatibility decorator redirect/pass behavior."""

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
        # The compatibility decorator validates through normalize_query_state,
        # which strips the value before checking the allow-list.
        resp = self._call("?sort=rank%20&direction=asc")
        self.assertEqual(resp.status_code, 200)

    def test_decorated_view_sees_stripped_common_params(self):
        @validate_common_params(ALLOWED_SORTS)
        def view(request):
            return HttpResponse(
                f"{request.GET['page']}:{request.GET['sort']}:"
                f"{request.GET['direction']}"
            )

        request = self.rf.get(
            "/coins/?page=%202%20&sort=%20rank%20&direction=%20asc%20"
        )
        resp = view(request)

        self.assertEqual(resp.content, b"2:rank:asc")

    def test_decorated_view_sees_blank_common_params_as_absent(self):
        @validate_common_params(ALLOWED_SORTS)
        def view(request):
            return HttpResponse(
                f"{request.GET.get('page', 'default-page')}:"
                f"{request.GET.get('sort', 'default-sort')}:"
                f"{request.GET.get('direction', 'default-direction')}"
            )

        request = self.rf.get("/coins/?page=&sort=&direction=")
        resp = view(request)

        self.assertEqual(
            resp.content,
            b"default-page:default-sort:default-direction",
        )


# ---------------------------------------------------------------------------
# D) get_common_params compatibility reader closure (common/utils.py)
# ---------------------------------------------------------------------------
class GetCommonParamsTests(SimpleTestCase):
    """Validate the compatibility reader closure."""

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

    def test_non_integer_page_raises_invalid_query_state(self):
        with self.assertRaises(InvalidQueryState):
            self._read("?page=abc", page_count=3)

    def test_whitespace_sort_stripped_downstream(self):
        self.assertEqual(
            self._read("?sort=rank%20&direction=asc", page_count=3),
            (1, "rank", "asc"),
        )

    def test_reader_uses_allowed_sorts_recorded_by_decorator(self):
        read = self.read

        @validate_common_params(ALLOWED_SORTS)
        def view(request):
            page, sort, direction = read(request, page_count=3)
            return HttpResponse(f"{page}:{sort}:{direction}")

        request = self.rf.get("/coins/?sort=coin&direction=desc")
        resp = view(request)

        self.assertEqual(resp.content, b"1:coin:desc")


# ---------------------------------------------------------------------------
# E) sort_link simple tag (common/templatetags/common_extras.py)
# ---------------------------------------------------------------------------
class SortLinkTests(SimpleTestCase):
    """Characterize the sort_link table-header link builder."""

    def _query_params(self, html):
        href_start = html.index("href='") + len("href='")
        href_end = html.index("'", href_start)
        href = unescape(html[href_start:href_end])
        return parse_qs(urlsplit(href).query, keep_blank_values=True)

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
        params = self._query_params(html)

        self.assertEqual(params["page"], ["2"])
        self.assertEqual(params["sort"], ["rank"])
        self.assertEqual(params["direction"], ["asc"])
        self.assertEqual(params["search"], ["btc"])

    def test_no_search_omits_search_param(self):
        html = str(sort_link("rank", 1, "coin", "asc", "", "Rank"))
        self.assertNotIn("search=", html)

    def test_search_value_is_url_encoded(self):
        html = str(sort_link("rank", 1, "coin", "asc", "a b&c=d?e", "Rank"))

        self.assertIn("search=a+b%26c%3Dd%3Fe", html)
        self.assertEqual(self._query_params(html)["search"], ["a b&c=d?e"])


class PaginationQueryTagTests(SimpleTestCase):
    """Validate the shared query-string builder used by pagination templates."""

    def _params(self, query):
        return parse_qs(query, keep_blank_values=True)

    def test_preserves_page_sort_direction(self):
        query = pagination_query(3, "price", "desc")

        self.assertEqual(
            self._params(query),
            {
                "page": ["3"],
                "sort": ["price"],
                "direction": ["desc"],
            },
        )

    def test_preserves_encoded_search_only_when_requested(self):
        query = pagination_query(2, "coin", "asc", "a b&c=d?e", True)

        self.assertIn("search=a+b%26c%3Dd%3Fe", query)
        self.assertEqual(self._params(query)["search"], ["a b&c=d?e"])

    def test_omits_search_when_not_requested(self):
        query = pagination_query(2, "coin", "asc", "a b&c=d?e", False)

        self.assertNotIn("search", self._params(query))


# ---------------------------------------------------------------------------
# E) Pagination partial (common/templates/common/partials/pagination.html)
# ---------------------------------------------------------------------------
class PaginationPartialTests(SimpleTestCase):
    """Characterize the shared pagination partial rendering."""

    def setUp(self):
        self.rf = RequestFactory()
        self.paginator = Paginator(list(range(25)), 10)  # 3 pages

    def _render(self, page_number, **extra_context):
        request = self.rf.get("/coins/search/")
        context = {
            "page_obj": self.paginator.page(page_number),
            "sort": "rank",
            "direction": "asc",
            "send_search": True,
            "search_query": "btc",
        }
        context.update(extra_context)
        return render_to_string(
            "common/partials/pagination.html",
            context,
            request=request,
        )

    def _hrefs(self, html):
        hrefs = []
        start = 0
        while True:
            href_start = html.find('href="', start)
            if href_start == -1:
                break
            href_start += len('href="')
            href_end = html.index('"', href_start)
            hrefs.append(unescape(html[href_start:href_end]))
            start = href_end + 1
        return hrefs

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

    def test_omits_back_link_by_default(self):
        html = self._render(1)
        self.assertNotIn("Back to Market", html)
        self.assertNotIn("btn btn-secondary", html)

    def test_renders_optional_generic_back_link(self):
        html = self._render(
            1,
            pagination_back_url="/portfolio/",
            pagination_back_label="Back to Portfolio",
        )

        self.assertIn("Back to Portfolio", html)
        self.assertIn('href="/portfolio/"', html)

    def test_search_query_is_url_encoded_in_partial(self):
        request = self.rf.get("/coins/search/")
        html = render_to_string(
            "common/partials/pagination.html",
            {
                "page_obj": self.paginator.page(1),
                "sort": "rank",
                "direction": "asc",
                "send_search": True,
                "search_query": "a b&c=d?e",
            },
            request=request,
        )

        self.assertIn("search=a+b%26c%3Dd%3Fe", html)
        next_href = next(
            href
            for href in self._hrefs(html)
            if href.startswith("/coins/search/?page=2")
        )
        params = parse_qs(urlsplit(next_href).query, keep_blank_values=True)
        self.assertEqual(params["search"], ["a b&c=d?e"])

    def test_search_query_should_be_url_encoded_in_partial(self):
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

        self.assertIn("search=a+b", html)
