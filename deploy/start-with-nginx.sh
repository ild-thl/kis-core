#!/bin/bash
# Server with the bundled nginx, see deploy/nginx/default.conf.
# Run from the repo root: bash deploy/start-with-nginx.sh [up|down|restart]
cd "$(dirname "$0")/.." || exit 1

COMPOSE_FILES="-f docker-compose.yml -f deploy/docker-compose.server.yml -f deploy/docker-compose.prod.yml"

# Starts only the workers of these modules.
modules=$(grep -E '^MODULES[[:space:]]*=' .env 2>/dev/null | tail -1 | cut -d= -f2- | cut -d'#' -f1 | tr -d " \"'")
export COMPOSE_PROFILES="${modules:-aia,tools}"
echo "Profiles: $COMPOSE_PROFILES"

CMD=${1:-up}

[ "$CMD" = "down" ] || [ "$CMD" = "restart" ] && docker compose $COMPOSE_FILES down --remove-orphans
[ "$CMD" = "down" ] && exit 0

PRODUCTION=true docker compose $COMPOSE_FILES up -d --build
docker image prune -f
# Without a size limit the prune drops the unshared build stages, so npm ci ran again on every frontend change.
docker builder prune -f --keep-storage 8GB
