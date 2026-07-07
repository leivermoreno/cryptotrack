#!/usr/bin/env sh
set -eu

python manage.py migrate --noinput
python manage.py createcachetable

# CoinGecko availability should not block a deploy; views degrade gracefully.
python manage.py sync_supported_coins || true
