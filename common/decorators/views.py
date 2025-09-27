from functools import wraps

from django.shortcuts import redirect


def validate_common_params(allowed_sorts):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            request = args[0]
            page = request.GET.get("page", "")
            sort = request.GET.get("sort", "").strip()
            direction = request.GET.get("direction", "").strip()
            invalid = False
            if page:
                try:
                    page = int(page)
                    if page < 1:
                        raise ValueError
                except ValueError:
                    invalid = True

            if sort or direction:
                if sort not in allowed_sorts or direction not in ["asc", "desc"]:
                    invalid = True

            if invalid:
                return redirect(request.path)

            return func(*args, **kwargs)

        return wrapper

    return decorator
