#!/bin/bash
# Starts askFrancis on a server, with the bundled Caddy when AUTO_HTTPS=true is in the .env.
# Run from the repo root: bash deploy/start.sh [up|down|restart]
# shellcheck source=deploy/common.sh
source "$(dirname "$0")/common.sh"
echo "Profiles: $COMPOSE_PROFILES"

CMD=${1:-up}

if [ "$CMD" = "down" ] || [ "$CMD" = "restart" ]; then
    compose down --remove-orphans
fi
[ "$CMD" = "down" ] && exit 0

compose up -d --build --remove-orphans
proxy_reload
docker image prune -f
# Without a size limit the prune drops the unshared build stages, so npm ci ran again on every frontend change.
docker builder prune -f --keep-storage 8GB
