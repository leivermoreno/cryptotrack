from django.shortcuts import render
from django.views.generic import TemplateView
from coins.services import get_page_count, get_coin_list_with_data


class IndexView(TemplateView):
    template_name = "coins/index.html"

    def get(self, request):
        page_count = get_page_count()
        page = request.GET.get("page", "1")
        try:
            page = int(page)
        except ValueError:
            page = 1
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
