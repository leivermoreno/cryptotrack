from coins.services import ALLOWED_SORTS, ALLOWED_DIRECTIONS


def get_validated_query_params(request, page_count):
    page = request.GET.get("page", "1")
    sort = request.GET.get("sort", "rank")
    direction = request.GET.get("direction", "asc")
    redirect = False

    try:
        page = int(page)
        if page < 1:
            raise ValueError
        elif page > page_count:
            redirect = True
            page = page_count
    except ValueError:
        redirect = True
        page = 1

    if sort not in ALLOWED_SORTS or direction not in ALLOWED_DIRECTIONS:
        redirect = True
        sort = "rank"
        direction = "asc"

    return {
        "redirect": redirect,
        "query_string": f"?page={page}&sort={sort}&direction={direction}",
        "page": page,
        "sort": sort,
        "direction": direction,
    }
