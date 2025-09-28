def add_direction_sign(sort, direction):
    if direction == "desc":
        return f"-{sort}"
    return sort


def get_common_params(default_sort, default_direction):
    def func(request, page_count):
        page_count = page_count or 1
        page = int(request.GET.get("page", "1"))
        page = min(page_count, page)
        sort = request.GET.get("sort", default_sort)
        direction = request.GET.get("direction", default_direction)

        return page, sort, direction

    return func
