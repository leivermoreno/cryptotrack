# syntax=docker/dockerfile:1
#
# Multi-stage build with two consumable targets:
#   * dev  — full dev tooling (Ruff, pre-commit), source bind-mounted at runtime,
#            Django autoreload. Built by docker-compose (`target: dev`).
#   * prod — lean runtime: only requirements.txt, static baked in, non-root,
#            gunicorn. This is the LAST stage, so `docker build` / Railway (which
#            builds the final stage of the Dockerfile) produce the prod image.
#
# `dev` and `prod` both branch from `base` and never depend on each other, so a
# prod build never pulls in dev tooling and vice versa.

ARG PYTHON_VERSION=3.12-slim

# --------------------------------------------------------------------------- #
# base — shared foundation: interpreter, env, workdir, non-root user.
# --------------------------------------------------------------------------- #
FROM python:${PYTHON_VERSION} AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=crypto_track.settings
WORKDIR /app
# psycopg2-binary ships a self-contained wheel (bundled libpq), so no compiler
# or libpq-dev is required — the slim image is enough.
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

# --------------------------------------------------------------------------- #
# dev — development image. Source is bind-mounted by compose (not COPY'd) so
# edits hot-reload; installs the dev tooling on top of runtime deps.
# --------------------------------------------------------------------------- #
FROM base AS dev
ENV DJANGO_DEBUG=true
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
EXPOSE 8000
# Overridden by docker-compose; sensible default for `docker run` on this target.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# --------------------------------------------------------------------------- #
# builder — install runtime deps into an isolated venv so the final image
# carries only the venv, not pip's build/cache layers.
# --------------------------------------------------------------------------- #
FROM base AS builder
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt ./
RUN pip install -r requirements.txt

# --------------------------------------------------------------------------- #
# prod — final runtime image (default target for `docker build` and Railway).
# --------------------------------------------------------------------------- #
FROM base AS prod
ENV PATH="/opt/venv/bin:$PATH"
COPY --from=builder /opt/venv /opt/venv
COPY . .
# Bake hashed/compressed static assets into the image (WhiteNoise serves them at
# runtime from its manifest). collectstatic touches no DB/network; DEBUG is off
# here, so settings import needs these three vars — throwaway build-time values
# satisfy it without embedding real secrets.
RUN SECRET_KEY=build-time-collectstatic-only \
    CSRF_TRUSTED_ORIGINS=https://build.invalid \
    ALLOWED_HOSTS=build.invalid \
    python manage.py collectstatic --noinput
RUN chown -R app:app /app
USER app
EXPOSE 8000
# Railway injects $PORT; default to 8000 for a plain `docker run`. DB migrations,
# createcachetable and the coin-list sync run as a pre-deploy step, not here
# (see railway.json / docker-compose.yml), so this stays a pure server start.
CMD ["sh", "-c", "gunicorn crypto_track.wsgi:application --bind 0.0.0.0:${PORT:-8000}"]
