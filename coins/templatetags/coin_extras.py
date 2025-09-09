from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def sort_link(key, page, current_sort, current_direction, content):
    direction = "asc"
    arrow = ""
    if current_sort == key:
        if current_direction == "asc":
            direction = "desc"
            arrow = "&#8593;"
        else:
            arrow = "&#8595;"

    html_template = "<a class='text-decoration-none' href='?page={}&sort={}&direction={}'>{} {}</a>"
    html = format_html(html_template, page, key, direction, content, mark_safe(arrow))

    return html
