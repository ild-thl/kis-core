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

AUTO_HTTPS=$(env_get AUTO_HTTPS)
# Older .env files still use the former name PROXY.
[ -n "$AUTO_HTTPS" ] || AUTO_HTTPS=$(env_get PROXY)

# -f explicit so a COMPOSE_FILE from the .env cannot add anything.
COMPOSE_FILES=(-f docker-compose.yml -f deploy/docker-compose.server.yml)
if [ "$AUTO_HTTPS" = "true" ]; then
    COMPOSE_FILES+=(-f deploy/docker-compose.proxy.yml)
fi

# Starts only the workers of these modules.
modules=$(env_get MODULES | tr -d ' ')
export COMPOSE_PROFILES="${modules:-aia,tools}"

export PRODUCTION=true

compose() {
    docker compose "${COMPOSE_FILES[@]}" "$@"
}

# Caddy keeps running across deploys, so a changed Caddyfile only arrives through a reload.
proxy_reload() {
    if [ "$AUTO_HTTPS" = "true" ]; then
        compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile
    fi
}
