import math

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from coins.models import Coin, Watchlist
from coins.services import (
    get_page_count,
    get_coin_list_with_market,
    RESULTS_PAGE,
    ALLOWED_SORTS,
)
from common.decorators.views import validate_common_params
from common.utils import get_common_params

validate_common_params = validate_common_params(ALLOWED_SORTS)
get_common_params = get_common_params(default_sort="rank", default_direction="asc")


@validate_common_params
def render_index(request):
    # manual pagination and redirect because data comes from external API
    page_count = get_page_count()
    page, sort, direction = get_common_params(request, page_count=page_count)

    coin_list = get_coin_list_with_market(page, sort, direction)
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


@validate_common_params
def render_search(request):
    search_query = request.GET.get("search", "").strip()
    if not search_query:
        return redirect(reverse("coins:index"))

    cg_id_list = Coin.objects.filter(
        Q(name__icontains=search_query) | Q(symbol__icontains=search_query)
    ).values_list("cg_id", flat=True)
    page_count = math.ceil(len(cg_id_list) / RESULTS_PAGE)
    page, sort, direction = get_common_params(request, page_count=page_count)
    page_obj = Paginator(cg_id_list, RESULTS_PAGE).page(page)
    coin_list = get_coin_list_with_market(1, sort, direction, ids=page_obj.object_list)
    user_watchlist = list(Watchlist.get_coin_ids_for_user(request.user.id))
    return render(
        request,
        "coins/search.html",
        context={
            "coin_list": coin_list,
            "search_query": search_query,
            "page_obj": page_obj,
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

    next_url = request.POST.get("next") or reverse("coins:index")
    return redirect(next_url)


@login_required
@validate_common_params
def render_watchlist(request):
    watchlist = Watchlist.get_coin_ids_for_user(request.user.id)
    paginator = Paginator(watchlist, 10)
    page, sort, direction = get_common_params(request, page_count=paginator.num_pages)
    page_obj = paginator.page(page)
    watchlist = page_obj.object_list
    coin_list = []
    if watchlist:
        coin_list = get_coin_list_with_market(1, sort, direction, ids=watchlist)

    return render(
        request,
        "coins/watchlist.html",
        context={
            "coin_list": coin_list,
            "sort": sort,
            "direction": direction,
            "page_obj": page_obj,
        },
    )
