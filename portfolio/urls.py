from django.urls import path

from . import views

app_name = "portfolio"
urlpatterns = [
    path(
        "add/<int:coin_id>", views.create_portfolio_transaction, name="add_transaction"
    ),
    path(
        "edit/<int:coin_id>/<int:transaction_id>",
        views.create_portfolio_transaction,
        name="edit_transaction",
    ),
]
