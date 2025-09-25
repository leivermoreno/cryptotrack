def get_common_params(request, page_count):
    page_count = page_count or 1
    page = int(request.GET.get("page", "1"))
    page = min(page_count, page)
    sort = request.GET.get("sort", "rank")
    direction = request.GET.get("direction", "asc")

    return page, sort, direction
