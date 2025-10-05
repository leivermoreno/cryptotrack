from django.urls import path

from . import views

app_name = "portfolio"
urlpatterns = [
    path("", views.portfolio_overview, name="overview"),
    path(
        "add/<int:coin_id>", views.create_portfolio_transaction, name="add_transaction"
    ),
    path("add/<cg_id>/", views.create_portfolio_transaction, name="add_transaction_cg"),
    path(
        "edit/<int:coin_id>/<int:transaction_id>",
        views.create_portfolio_transaction,
        name="edit_transaction",
    ),
    path(
        "delete/<int:coin_id>/<int:transaction_id>",
        views.delete_portfolio_transaction,
        name="delete_transaction",
    ),
    path("all/", views.show_all_transactions, name="all_transactions"),
]
