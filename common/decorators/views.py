from functools import wraps

from django.shortcuts import redirect

from coins.services import ALLOWED_SORTS, ALLOWED_DIRECTIONS


def validate_common_params(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        request = args[0]
        page = request.GET.get("page", "1")
        sort = request.GET.get("sort", "rank")
        direction = request.GET.get("direction", "asc")
        invalid = False
        try:
            page = int(page)
            if page < 1:
                raise ValueError
        except ValueError:
            page = 1
            invalid = True

        if sort not in ALLOWED_SORTS or direction not in ALLOWED_DIRECTIONS:
            sort = "rank"
            direction = "asc"
            invalid = True

        if invalid:
            return redirect(
                f"{request.path}?page={page}&sort={sort}&direction={direction}"
            )

        return func(*args, **kwargs)

    return wrapper
