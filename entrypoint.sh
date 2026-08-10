#!/bin/sh
set -e

# Fail with a readable message instead of a Django traceback 20 lines deep when
# the deploy .env is missing a key.
for var in DJANGO_SECRET DB_NAME DB_USER DB_PASSWORD; do
    eval "value=\$$var"
    if [ -z "$value" ]; then
        echo "FATAL: required environment variable $var is not set" >&2
        exit 1
    fi
done

echo "Running collectstatic..."
python manage.py collectstatic --noinput

echo "Starting gunicorn..."
# 2 vCPU box shared with staging, so (2 * cores) + 1 is too many; 3 workers with
# a 60s timeout matches nginx's proxy_read_timeout.
exec gunicorn web_fuki.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout 60 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile -
