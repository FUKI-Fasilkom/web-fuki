#!/bin/sh
set -e

echo "Running collectstatic..."
python manage.py collectstatic --noinput

echo "Starting gunicorn..."
exec gunicorn web_fuki.wsgi:application --bind 0.0.0.0:8000