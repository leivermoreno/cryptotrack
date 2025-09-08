from django import template
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

    href = f"?page={page}&sort={key}&direction={direction}"
    html = f"<a class='text-decoration-none' href='{href}'>{content} {arrow}</a>"

    return mark_safe(html)
