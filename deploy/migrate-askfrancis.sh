#!/usr/bin/env bash
# One-time move from the KIS names to askFrancis: copies volumes, renames database and role, rewrites .env.
# Run from anywhere with the old stack stopped (docker compose down, without -v): deploy/migrate-askfrancis.sh [old project name]
set -euo pipefail
cd "$(dirname "$0")/.."

OLD=${1:-$(basename "$PWD")}
NEW=askfrancis

[ -f .env ] || { echo ".env fehlt"; exit 1; }
# Only containers of the old compose project count, a separate kis-tunnel may keep running.
if [ -n "$(docker ps -aq --filter label=com.docker.compose.project=$OLD)" ]; then
    echo "Alte Container gibt es noch. Erst: docker rm -f \$(docker ps -aq --filter label=com.docker.compose.project=$OLD)"; exit 1
fi

# Reads one key from .env, empty if missing.
read_env() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- || true; }

cp .env ".env.vor-askfrancis"
echo "Sicherung: .env.vor-askfrancis"

# 1. Volumes: copy, the old ones stay as a fallback.
for v in postgres-data storage minio-data celerybeat caddy-data caddy-config; do
    src="${OLD}_kis-$v"; dst="${NEW}_askf-$v"
    docker volume inspect "$src" >/dev/null 2>&1 || { echo "übersprungen: $src gibt es nicht"; continue; }
    if docker volume inspect "$dst" >/dev/null 2>&1; then echo "übersprungen: $dst gibt es schon"; continue; fi
    docker volume create --label com.docker.compose.project="$NEW" --label com.docker.compose.volume="askf-$v" "$dst" >/dev/null
    docker run --rm -v "$src":/from:ro -v "$dst":/to alpine sh -c 'cp -a /from/. /to/'
    echo "kopiert: $src -> $dst"
done

# 2. Database and role, through a temporary superuser because a session cannot rename its own role.
PGU=$(read_env POSTGRES_USER); PGU=${PGU:-kis}
PGD=$(read_env POSTGRES_DB); PGD=${PGD:-kis}
PW=$(read_env POSTGRES_PASSWORD); PW=${PW:-askf-local-dev}
NU=${PGU//kis/askf}; ND=${PGD//kis/askf}
if [ "$PGU" != "$NU" ] || [ "$PGD" != "$ND" ]; then
    docker compose up -d postgres
    until docker exec askf-postgres pg_isready -U "$PGU" -q 2>/dev/null; do sleep 1; done
    psql_as() { docker exec -i askf-postgres psql -U "$1" -d postgres -v ON_ERROR_STOP=1 -q; }
    echo 'CREATE ROLE askf_migrate SUPERUSER LOGIN;' | psql_as "$PGU"
    {
        [ "$PGU" != "$NU" ] && echo "ALTER ROLE \"$PGU\" RENAME TO \"$NU\";"
        [ "$PGD" != "$ND" ] && echo "ALTER DATABASE \"$PGD\" RENAME TO \"$ND\";"
        echo "ALTER ROLE \"$NU\" PASSWORD '${PW//\'/\'\'}';"
    } | psql_as askf_migrate
    echo 'DROP ROLE askf_migrate;' | psql_as "$NU"
    docker compose stop postgres
    echo "Datenbank: $PGU/$PGD -> $NU/$ND"
fi

# 3. .env: new key names, new database names, the bucket stays where the files are.
perl -pi -e "
s/^KIS_(SECRETS_KEY|EXPORT_KEY)=/ASKF_\$1=/;
s/^POSTGRES_USER=\Q$PGU\E\$/POSTGRES_USER=$NU/;
s/^POSTGRES_DB=\Q$PGD\E\$/POSTGRES_DB=$ND/;
s#^(DATABASE_URL=postgresql://)\Q$PGU\E:#\${1}$NU:#;
s#^(DATABASE_URL=.*/)\Q$PGD\E\$#\${1}$ND#;
s/\bkis-(redis|postgres|backend|langfuse|minio)\b/askf-\$1/g;
" .env
grep -q '^S3_BUCKET=' .env || echo 'S3_BUCKET=kis' >> .env
echo ".env angepasst"

echo
echo "Fertig. Jetzt starten wie sonst. Läuft alles, die alten Volumes löschen:"
docker volume ls --format '{{.Name}}' | grep "^${OLD}_kis-" | sed 's/^/  docker volume rm /' || true
attached=$(docker network inspect "${OLD}_default" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null || true)
[ -n "$attached" ] && echo "Noch am alten Netz ${OLD}_default: $attached -> mit docker network connect ${NEW}_default <name> umhängen"
exit 0
