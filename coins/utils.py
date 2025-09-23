from coins.services import ALLOWED_SORTS, ALLOWED_DIRECTIONS


def get_validated_query_params(request, page_count):
    page = request.GET.get("page", "1")
    sort = request.GET.get("sort", "rank")
    direction = request.GET.get("direction", "asc")
    redirect = False
    query_dict = None

    if page_count == 0:
        page_count = 1
    else:
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

    if redirect:
        query_dict = {
            "page": page,
            "sort": sort,
            "direction": direction,
        }

    return {
        "redirect": redirect,
        "page": page,
        "sort": sort,
        "direction": direction,
        "query_dict": query_dict,
    }
