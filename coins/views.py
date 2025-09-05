from pprint import pprint
from django.shortcuts import render
from django.views.generic import TemplateView
from coins.services import get_coin_list


class IndexView(TemplateView):
    template_name = "coins/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["coin_list"] = get_coin_list()
        pprint(context["coin_list"])
        return context
