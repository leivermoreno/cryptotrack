from django.urls import path
from coins.views import (
    render_index,
    add_remove_to_watchlist,
    render_watchlist,
    render_search,
)

app_name = "coins"
urlpatterns = [
    path("", render_index, name="index"),
    path(
        "add_remove_to_watchlist/<str:cg_id>/",
        add_remove_to_watchlist,
        name="add_remove_to_watchlist",
    ),
    path("watchlist/", render_watchlist, name="watchlist"),
    path("search/", render_search, name="search"),
]
