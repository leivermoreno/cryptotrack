from django.urls import path
from coins.views import IndexView

app_name = "coins"
urlpatterns = [path("", IndexView.as_view(), name="index")]
