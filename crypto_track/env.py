"""Environment-variable access helpers.

Centralizes reading configuration from the process environment so that:

- required variables fail with a clear ``ImproperlyConfigured`` message instead
  of a raw ``KeyError``;
- optional variables have explicit defaults;
- value coercion (strip, bool, int, comma-separated list) lives in one place.

These are the primitives for env-driven settings only. Settings constants that
do not vary per environment stay hardcoded in ``settings.py``.

A value that is unset or empty after stripping is treated as "not provided": the
default is returned, or ``ImproperlyConfigured`` is raised when no default is
given.
"""

import os

from django.core.exceptions import ImproperlyConfigured

# Sentinel marking a required variable, i.e. no default was supplied.
_UNSET = object()

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _raw(name):
    """Return the stripped value of ``name``, or ``""`` if unset/blank."""
    return os.environ.get(name, "").strip()


def _missing(name, default):
    """Return ``default`` or raise for a required, unset variable."""
    if default is _UNSET:
        raise ImproperlyConfigured(
            f"Required environment variable {name!r} is not set."
        )
    return default


def env(name, default=_UNSET):
    """Return the stripped string value of environment variable ``name``."""
    value = _raw(name)
    if not value:
        return _missing(name, default)
    return value


def env_bool(name, default=_UNSET):
    """Return ``name`` coerced to a bool.

    Accepts (case-insensitively) ``1/true/yes/on`` and ``0/false/no/off``; any
    other non-empty value raises ``ImproperlyConfigured``.
    """
    value = _raw(name).lower()
    if not value:
        return _missing(name, default)
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ImproperlyConfigured(
        f"Environment variable {name!r} must be a boolean "
        f"(one of {sorted(_TRUE_VALUES | _FALSE_VALUES)}), got {value!r}."
    )


def env_int(name, default=_UNSET):
    """Return ``name`` coerced to an int, raising on non-integer values."""
    value = _raw(name)
    if not value:
        return _missing(name, default)
    try:
        return int(value)
    except ValueError:
        raise ImproperlyConfigured(
            f"Environment variable {name!r} must be an integer, got {value!r}."
        )


def env_list(name, default=_UNSET, separator=","):
    """Return ``name`` split on ``separator`` into a list of stripped, non-empty items."""
    value = _raw(name)
    if not value:
        return _missing(name, default)
    return [item.strip() for item in value.split(separator) if item.strip()]
