from django.shortcuts import render, redirect
from django.urls import reverse
from coins.services import get_page_count, get_coin_list_with_data, ALLOWED_SORTS


def render_index(request):
    page_count = get_page_count()
    page = request.GET.get("page", "1")
    first_page_url = reverse("coins:index")
    sort = request.GET.get("sort", "rank")
    direction = request.GET.get("direction", "asc")
    # manual pagination and redirect because data comes from external API
    redirect_url = None
    try:
        page = int(page)
    except ValueError:
        page = 0
    if page < 1:
        redirect_url = first_page_url
    elif page > page_count:
        redirect_url = f"{first_page_url}?page={page_count}"
    elif sort not in ALLOWED_SORTS or direction not in ["asc", "desc"]:
        redirect_url = reverse("coins:index", query={"page": page})

    if redirect_url:
        return redirect(redirect_url)

    page = min(page, get_page_count())
    coin_list = get_coin_list_with_data(page, sort, direction)

    return render(
        request,
        "coins/index.html",
        context={
            "page": page,
            "page_count": page_count,
            "coin_list": coin_list,
            "sort": sort,
            "direction": direction,
        },
    )
