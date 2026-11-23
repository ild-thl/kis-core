#!/bin/bash
# Deploys the latest main on the Hetzner box and keeps the site up while the images build.
# Started by the "Deploy Hetzner" workflow through a forced SSH command, the argument "force" skips the job check.

# The whole script sits in one function so bash has read it completely before git pull replaces the file.
main() {
    set -euo pipefail
    cd "$(dirname "$0")/.."

    local mode="${SSH_ORIGINAL_COMMAND:-${1:-normal}}"
    local files="-f docker-compose.yml -f deploy/docker-compose.server.yml -f deploy/docker-compose.prod.yml"
    log() { echo "[deploy] $*"; }
    free_gb() { df --output=avail -BG / | tail -1 | tr -dc '0-9'; }

    # A build needs room for the old and the new images at the same time.
    if [ "$(free_gb)" -lt 5 ]; then
        log "Less than 5 GB free, clearing the build cache."
        docker builder prune -f --keep-storage 4GB >/dev/null
    fi
    if [ "$(free_gb)" -lt 5 ]; then
        log "Still less than 5 GB free ($(free_gb) GB), aborting."
        exit 1
    fi
    log "Free disk: $(free_gb) GB"

    # Recreating the workers would kill running jobs.
    if [ "$mode" != "force" ]; then
        local db_user db_name active
        db_user=$(grep -E '^POSTGRES_USER=' .env | tail -1 | cut -d= -f2- | tr -d " \"'" || true)
        db_name=$(grep -E '^POSTGRES_DB=' .env | tail -1 | cut -d= -f2- | tr -d " \"'" || true)
        active=$(docker exec kis-postgres psql -U "${db_user:-kis}" -d "${db_name:-kis}" -tAc \
            "SELECT (SELECT count(*) FROM jobs WHERE status IN ('pending','queued','running'))
                  + (SELECT count(*) FROM aia_jobs WHERE status IN ('queued','running'))")
        if [ "$active" -gt 0 ]; then
            log "$active jobs are still active, aborting. Start again with force to deploy anyway."
            exit 1
        fi
        log "No active jobs."
    fi

    if [ "$(git branch --show-current)" != "main" ]; then
        log "The box is not on main, aborting."
        exit 1
    fi
    local old new
    old=$(git rev-parse --short HEAD)
    git fetch -q origin main
    git merge --ff-only -q origin/main
    new=$(git rev-parse --short HEAD)
    log "main $old -> $new"

    # The module workers carry a profile on the servers, Compose starts them only when it is named.
    local modules
    modules=$(grep -E '^MODULES[[:space:]]*=' .env 2>/dev/null | tail -1 | cut -d= -f2- | cut -d'#' -f1 | tr -d " \"'" || true)
    export COMPOSE_PROFILES="${modules:-aia,tools}"
    export PRODUCTION=true

    # The box has little memory, so the idle workers make room for the build and come back with the recreate.
    local workers
    workers=$(docker compose $files config --services | grep -E '^celery-' | tr '\n' ' ')
    log "Stopping the workers during the build: $workers"
    docker compose $files stop $workers

    log "Building images while the site keeps running."
    local oom_before oom_after
    oom_before=$(dmesg 2>/dev/null | grep -c 'Out of memory' || true)
    if ! docker compose $files build; then
        log "Build failed, starting the workers again with the old version."
        docker compose $files start $workers
        exit 1
    fi
    oom_after=$(dmesg 2>/dev/null | grep -c 'Out of memory' || true)
    if [ "$oom_after" -gt "$oom_before" ]; then
        log "WARNING: the kernel killed $((oom_after - oom_before)) process(es) for lack of memory during the build."
    else
        log "No process was killed for lack of memory during the build."
    fi
    docker compose $files up -d --remove-orphans

    # Mounted source code and the single-file nginx config only reach a fresh container.
    local apps
    apps=$(docker compose $files config --services | grep -E '^(backend|frontend|nginx|celery-.*)$' | tr '\n' ' ')
    log "Recreating: $apps"
    docker compose $files up -d --force-recreate --no-deps $apps

    docker image prune -f >/dev/null
    docker builder prune -f --keep-storage 8GB >/dev/null
    log "Free disk after cleanup: $(free_gb) GB"

    local domain code=000
    domain=$(grep -m1 -oE 'server_name [^ ;]+' deploy/nginx/default.conf | awk '{print $2}')
    for _ in $(seq 1 36); do
        code=$(curl -sk -o /dev/null -w '%{http_code}' --resolve "$domain:443:127.0.0.1" "https://$domain/" || true)
        if [ "$code" = "200" ]; then
            log "https://$domain answers 200, deploy of $new done."
            exit 0
        fi
        sleep 5
    done
    log "https://$domain did not answer 200 within 3 min (last: $code)."
    exit 1
}

main "$@"
exit
