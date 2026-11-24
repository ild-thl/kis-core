# shellcheck shell=bash
# Shared setup for start.sh and deploy.sh, sourced from both.

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

# Reads one value from the .env like Compose does, without running the file as a script.
env_get() {
    local value
    value=$(grep -E "^$1[[:space:]]*=" .env 2>/dev/null | tail -1 | cut -d= -f2-) || true
    value="${value#"${value%%[![:space:]]*}"}"
    case $value in
        \"*) value=${value#\"}; value=${value%%\"*} ;;
        \'*) value=${value#\'}; value=${value%%\'*} ;;
        *) value=$(printf '%s' "$value" | sed -E 's/[[:space:]]+#.*$//; s/[[:space:]]+$//') ;;
    esac
    printf '%s\n' "$value"
}

PROXY=$(env_get PROXY)

# -f explicit so a COMPOSE_FILE from the .env cannot add anything.
COMPOSE_FILES=(-f docker-compose.yml -f deploy/docker-compose.server.yml)
if [ "$PROXY" = "true" ]; then
    COMPOSE_FILES+=(-f deploy/docker-compose.proxy.yml)
fi

# Starts only the workers of these modules.
modules=$(env_get MODULES | tr -d ' ')
export COMPOSE_PROFILES="${modules:-aia,tools}"

# The HPC tunnel starts only when its SSH key is present.
hpc_key=${HPC_SSH_KEY:-$(env_get HPC_SSH_KEY)}
hpc_key=${hpc_key:-$HOME/.ssh/kis-hpc}
if [ -f "${hpc_key/#\~/$HOME}" ]; then
    COMPOSE_PROFILES="$COMPOSE_PROFILES,hpc"
fi

export PRODUCTION=true

compose() {
    docker compose "${COMPOSE_FILES[@]}" "$@"
}

# Caddy keeps running across deploys, so a changed Caddyfile only arrives through a reload.
proxy_reload() {
    if [ "$PROXY" = "true" ]; then
        compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile
    fi
}
