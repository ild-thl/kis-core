#!/bin/bash
# isy-kis-thl (THL server) — base + frontend, without nginx (the THL nginx handles that)
# Run from the repo root: bash deploy/start-thl.sh [up|down|restart]
cd "$(dirname "$0")/.." || exit 1

# -f explicit so a COMPOSE_FILE from the .env cannot add anything.
COMPOSE_FILES="-f docker-compose.yml -f deploy/docker-compose.server.yml"

# The module workers carry a profile on the servers, Compose starts them only when it is named.
MODULES_WERT=$(grep -E '^MODULES[[:space:]]*=' .env 2>/dev/null | tail -1 | cut -d= -f2- | cut -d'#' -f1 | tr -d " \"'")
export COMPOSE_PROFILES="${MODULES_WERT:-aia,tools}"
# The HPC tunnel starts only when the GWDG key is present.
[ -f "${HPC_SSH_KEY:-$HOME/.ssh/kis-hpc}" ] && COMPOSE_PROFILES="$COMPOSE_PROFILES,hpc"
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
