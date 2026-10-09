#!/bin/sh
set -eu

# Migrations run as the schema owner. The web app then connects as DB_USER, a role
# that can read and write rows but can't change tables or bypass row-level security.
DB_USER="$DB_OWNER_USER" DB_PASSWORD="$DB_OWNER_PASSWORD" python manage.py migrate --noinput

exec gunicorn lerp.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${WEB_CONCURRENCY:-2}" \
    --no-control-socket \
    --access-logfile -
