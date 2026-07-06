from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from common.utils import build_query_string

register = template.Library()


def get_decimal_formatted(value, precision, significant_digits):
    value_str = f"{value:.{precision}f}".rstrip("0")
    if value_str == "0.":
        return "0"

    first_significant_idx = None
    for idx, digit in enumerate(value_str):
        if digit not in ("0", "."):
            first_significant_idx = idx
            break

    last_significant_idx = first_significant_idx + significant_digits - 1
    last_significant_idx = min(last_significant_idx, len(value_str) - 1)
    return value_str[: last_significant_idx + 1]


def _to_decimal(value):
    if value is None:
        return None

    if isinstance(value, str) and not value.strip():
        return None

    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None

    if not decimal_value.is_finite():
        return None

    return decimal_value


@register.filter(is_safe=True)
def format_number(value):
    value = _to_decimal(value)
    if value is None:
        return "-"

    sign = "-" if value < 0 else ""
    magnitude = abs(value)

    if magnitude == int(magnitude):
        output = f"{magnitude:,.0f}"
    elif magnitude >= 1:
        output = f"{magnitude:,.2f}"
    else:
        output = get_decimal_formatted(magnitude, precision=10, significant_digits=4)

    return f"{sign}{output}"


@register.filter(is_safe=True)
def format_amount(value):
    formatted_value = format_number(value)
    if formatted_value == "-":
        return formatted_value

    return f"${formatted_value}"


@register.filter(is_safe=True)
def format_percentage(value):
    value = _to_decimal(value)
    if value is None:
        return "-"
    else:
        val = f"{value:.2f}"
        if val in {"0.00", "-0.00"}:
            val = "0"
        return val + "%"


@register.filter(is_safe=True)
def percentage_change_class(value):
    value = _to_decimal(value)
    if value is None:
        return ""

    rounded_value = Decimal(f"{value:.2f}")
    if rounded_value == 0:
        return ""
    if rounded_value < 0:
        return "text-danger"

    return "text-success"


@register.simple_tag
def sort_link(key, page, current_sort, current_direction, search, content):
    direction = "asc"
    arrow = ""
    if current_sort == key:
        if current_direction == "asc":
            direction = "desc"
            arrow = "&#8593;"
        else:
            arrow = "&#8595;"

    params = {
        "page": page,
        "sort": key,
        "direction": direction,
    }
    if search:
        params["search"] = search

    html_template = "<a class='text-decoration-none' href='?{}'>{} {}</a>"
    html = format_html(
        html_template, build_query_string(params), content, mark_safe(arrow)
    )

    return html


@register.simple_tag
def pagination_query(page, sort, direction, search=None, include_search=False):
    params = {
        "page": page,
        "sort": sort,
        "direction": direction,
    }
    if include_search and search:
        params["search"] = search
    return build_query_string(params)
