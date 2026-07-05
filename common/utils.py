from django.utils.http import url_has_allowed_host_and_scheme


def add_direction_sign(sort, direction):
    if direction == "desc":
        return f"-{sort}"
    return sort


def get_safe_redirect_url(request, redirect_to):
    if redirect_to is None:
        return None

    redirect_to = redirect_to.strip()
    if not redirect_to:
        return None

    if url_has_allowed_host_and_scheme(
        url=redirect_to,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect_to
    return None


def get_common_params(default_sort, default_direction):
    def func(request, page_count):
        page_count = page_count or 1
        page = int(request.GET.get("page", "1"))
        page = min(page_count, page)
        sort = request.GET.get("sort", default_sort)
        direction = request.GET.get("direction", default_direction)

        return page, sort, direction

    return func
