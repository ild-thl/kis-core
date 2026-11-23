#!/bin/bash
# Hetzner server — base + production nginx
# Run from the repo root: bash deploy/start-nginx.sh [up|down|restart]
cd "$(dirname "$0")/.." || exit 1

COMPOSE_FILES="-f docker-compose.yml -f deploy/docker-compose.server.yml -f deploy/docker-compose.prod.yml"

# The module workers carry a profile on the servers, Compose starts them only when it is named.
MODULES_WERT=$(grep -E '^MODULES[[:space:]]*=' .env 2>/dev/null | tail -1 | cut -d= -f2- | cut -d'#' -f1 | tr -d " \"'")
export COMPOSE_PROFILES="${MODULES_WERT:-aia,tools}"
echo "Modul-Profil: $COMPOSE_PROFILES"

# Without a size limit the prune drops the unshared build stages, so npm ci ran again on every frontend change.
CMD=${1:-up}

if [ "$CMD" = "down" ]; then
    docker compose $COMPOSE_FILES down --remove-orphans
elif [ "$CMD" = "restart" ]; then
    docker compose $COMPOSE_FILES down --remove-orphans
    PRODUCTION=true docker compose $COMPOSE_FILES up -d --build
    docker image prune -f
    docker builder prune -f --keep-storage 8GB
else
    PRODUCTION=true docker compose $COMPOSE_FILES up -d --build
    docker image prune -f
    docker builder prune -f --keep-storage 8GB
fi
