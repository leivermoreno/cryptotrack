from functools import wraps

from django.shortcuts import redirect

from common.utils import (
    REQUEST_ALLOWED_SORTS_ATTR,
    InvalidQueryState,
    normalize_query_state,
)


def _first_allowed_sort(allowed_sorts):
    return next(iter(allowed_sorts))


def _sync_normalized_query_params(request, state):
    query = request.GET.copy()
    changed = False

    for key, value in (
        ("page", state.page),
        ("sort", state.sort),
        ("direction", state.direction),
    ):
        raw_value = request.GET.get(key)
        if raw_value is None:
            continue

        if raw_value.strip():
            normalized_value = str(value)
            if raw_value != normalized_value:
                query[key] = normalized_value
                changed = True
            continue

        query.pop(key, None)
        changed = True

    if changed:
        request.GET = query


def validate_common_params(allowed_sorts):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            request = args[0]
            try:
                state = normalize_query_state(
                    request,
                    allowed_sorts=allowed_sorts,
                    default_sort=_first_allowed_sort(allowed_sorts),
                    default_direction="asc",
                )
            except InvalidQueryState:
                return redirect(request.path)

            _sync_normalized_query_params(request, state)
            setattr(request, REQUEST_ALLOWED_SORTS_ATTR, allowed_sorts)
            return func(*args, **kwargs)

        return wrapper

    return decorator
