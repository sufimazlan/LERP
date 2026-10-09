#!/bin/sh
# Runs once, when the database volume is first created.
#
# lerp_owner owns the schema and runs migrations. lerp_app is what the web app uses:
# it can read and write rows, but it can't alter or own tables, and neither role can
# bypass row-level security.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v owner_pw="$LERP_OWNER_PASSWORD" -v app_pw="$LERP_APP_PASSWORD" <<'SQL'
CREATE ROLE lerp_owner LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'owner_pw';
CREATE ROLE lerp_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'app_pw';
ALTER DATABASE :"DBNAME" OWNER TO lerp_owner;
GRANT USAGE ON SCHEMA public TO lerp_app;
ALTER DEFAULT PRIVILEGES FOR ROLE lerp_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lerp_app;
ALTER DEFAULT PRIVILEGES FOR ROLE lerp_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO lerp_app;
SQL
