from django.urls import path
from coins.views import render_index

app_name = "coins"
urlpatterns = [path("", render_index, name="index")]
