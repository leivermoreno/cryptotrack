from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect
from django.urls import reverse
from coins.services import (
    get_page_count,
    get_coin_list_with_data,
    get_simple_coin_data,
    ALLOWED_SORTS,
    ALLOWED_DIRECTIONS,
)
from coins.models import Watchlist


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
    elif sort not in ALLOWED_SORTS or direction not in ALLOWED_DIRECTIONS:
        redirect_url = reverse("coins:index", query={"page": page})

    if redirect_url:
        return redirect(redirect_url)

    page = min(page, get_page_count())
    coin_list = get_coin_list_with_data(page, sort, direction)
    user_watchlist = (
        Watchlist.get_coin_ids_for_user(request.user.id)
        if request.user.is_authenticated
        else []
    )

    return render(
        request,
        "coins/index.html",
        context={
            "page": page,
            "page_count": page_count,
            "coin_list": coin_list,
            "sort": sort,
            "direction": direction,
            "user_watchlist": user_watchlist,
        },
    )


@login_required
@require_POST
def add_remove_to_watchlist(request, cg_id):
    coin = get_simple_coin_data(cg_id)
    if coin:
        watchlist, created = Watchlist.objects.get_or_create(
            user_id=request.user.id, coin_id=coin.id
        )
        if not created:
            watchlist.delete()

    return redirect(reverse("coins:index"))
