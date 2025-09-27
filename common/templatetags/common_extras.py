from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def multiply(value, arg):
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ""


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


@register.filter(is_safe=True)
def format_number(value):
    if value is None:
        return "-"
    elif value == int(value):
        output = f"{value:,.0f}"
    elif value >= 1:
        output = f"{value:,.2f}"
    else:
        output = get_decimal_formatted(value, precision=10, significant_digits=4)

    return f"{output}"


@register.filter(is_safe=True)
def format_amount(value):
    return f"${format_number(value)}"


@register.filter(is_safe=True)
def format_percentage(value):
    if value is None:
        return "-"
    else:
        val = f"{value:.2f}"
        if val == "0.00":
            val = "0"
        return val + "%"


@register.filter(is_safe=True)
def percentage_change_class(value):
    if value is None:
        return ""
    if value <= 0:
        return "text-danger"
    else:
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

    if search:
        search = f"&search={search}"

    html_template = "<a class='text-decoration-none' href='?page={}&sort={}&direction={}{}'>{} {}</a>"
    html = format_html(
        html_template, page, key, direction, search, content, mark_safe(arrow)
    )

    return html
