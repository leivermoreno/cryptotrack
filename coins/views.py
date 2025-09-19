from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from django.urls import reverse
from coins.services import (
    get_page_count,
    get_coin_list_with_data,
)
from coins.models import Coin, Watchlist
from coins.utils import get_validated_query_params


def render_index(request):
    # manual pagination and redirect because data comes from external API
    page_count = get_page_count()
    params = get_validated_query_params(request, page_count)
    if params["redirect"]:
        redirect_url = reverse("coins:index") + params["query_string"]
        return redirect(redirect_url)

    page = params["page"]
    sort = params["sort"]
    direction = params["direction"]
    coin_list = get_coin_list_with_data(page, sort, direction)
    user_watchlist = (
        list(Watchlist.get_coin_ids_for_user(request.user.id))
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
    try:
        coin = Coin.objects.get(cg_id=cg_id)
        watchlist, created = Watchlist.objects.get_or_create(
            user_id=request.user.id, coin_id=coin.id
        )
        if not created:
            watchlist.delete()
    except Coin.DoesNotExist:
        pass

    next_url = request.POST.get("next", reverse("coins:index"))
    return redirect(next_url)


@login_required
def render_watchlist(request):
    watchlist = Watchlist.get_coin_ids_for_user(request.user.id)
    paginator = Paginator(watchlist, 10)

    params = get_validated_query_params(request, paginator.num_pages)
    if params["redirect"]:
        redirect_url = reverse("coins:watchlist") + params["query_string"]
        return redirect(redirect_url)
    page = params["page"]
    sort = params["sort"]
    direction = params["direction"]
    page_obj = paginator.page(page)
    watchlist = page_obj.object_list
    coins = []
    if watchlist:
        coins = get_coin_list_with_data(1, sort, direction, ids=watchlist)

    return render(
        request,
        "coins/watchlist.html",
        context={
            "coin_list": coins,
            "sort": sort,
            "direction": direction,
            "page_obj": page_obj,
        },
    )
