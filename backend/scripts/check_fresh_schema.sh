#!/usr/bin/env bash
# Builds the schema ONCE from scratch and reports whether it goes through.
#
# Why the ordinary start does not cover this: on a grown database all tables are
# long since there, so it never shows when a statement touches a table that is
# only created further down. A new university starts with an EMPTY database, and
# there something like that aborts the whole start
# ("relation ... does not exist", Application startup failed).
#
# Happened exactly that way on the server on 2026-08-10. So run this before every
# larger schema rework.
#
# Two kinds of error, two different fixes:
#   * ALTER TABLE ... ADD COLUMN  -> needed on a fresh database too. The target
#     table belongs BEFORE its use.
#   * UPDATE / DELETE on legacy data -> on an empty database there is nothing to
#     clean up. Skip it with _table_exists().
#
# It always shows only the NEXT error. Call it again after every fix until
# "SCHEMA OK" appears.
#
# Call from the project root:  backend/scripts/check_fresh_schema.sh
set -euo pipefail

DB="${FRESH_SCHEMA_DB:-askf_schematest}"
PW=$(grep -m1 '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)

if [ -z "$PW" ]; then
    echo "POSTGRES_PASSWORD steht nicht in .env" >&2
    exit 1
fi

echo "Lege $DB neu an..."
docker exec askf-postgres psql -U askf -d postgres -q \
    -c "DROP DATABASE IF EXISTS $DB" \
    -c "CREATE DATABASE $DB" >/dev/null

echo "Baue das Schema von null auf..."
docker compose run --rm --no-deps \
    -e DATABASE_URL="postgresql://askf:${PW}@postgres:5432/${DB}" \
    backend python -c "from src.core.db.schema import init_db; init_db(); print('SCHEMA OK auf leerer Datenbank')" \
    2>&1 | grep -vE '^time=|Maschine erkannt|orphan containers'

# A comparison against the grown database used to sit here and is gone again: it
# carries dead columns from abandoned attempts, and those showed up as an alleged
# gap on every run. Whoever really wants to compare does it by hand and looks at
# every line.

echo
echo "Raeume $DB wieder ab."
docker exec askf-postgres psql -U askf -d postgres -q -c "DROP DATABASE IF EXISTS $DB" >/dev/null
