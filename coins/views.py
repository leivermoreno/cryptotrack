from django.shortcuts import render, redirect
from django.urls import reverse
from coins.services import get_page_count, get_coin_list_with_data


def render_index(request):
    page_count = get_page_count()
    page = request.GET.get("page", "1")
    first_page = reverse("coins:index")
    # manual pagination and redirect because data comes from external API
    redirect_url = None
    try:
        page = int(page)
    except ValueError:
        page = 0
    if page < 1:
        redirect_url = first_page
    elif page > page_count:
        redirect_url = f"{first_page}?page={page_count}"

    if redirect_url:
        return redirect(redirect_url)

    page = min(page, get_page_count())
    coin_list = get_coin_list_with_data(page)

    return render(
        request,
        "coins/index.html",
        context={
            "page": page,
            "page_count": page_count,
            "coin_list": coin_list,
        },
    )
