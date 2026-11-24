#!/bin/bash
# Deploys the latest main on the server and keeps the site up while the images build.
# Started by the "Deploy" workflow through a forced SSH command, the argument "force" skips the job check.

# The whole script sits in one function so bash has read it completely before git pull replaces the file.
main() {
    set -euo pipefail
    # shellcheck source=deploy/common.sh
    source "$(dirname "$0")/common.sh"

    local mode="${SSH_ORIGINAL_COMMAND:-${1:-normal}}"
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
        db_user=$(env_get POSTGRES_USER)
        db_name=$(env_get POSTGRES_DB)
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
        log "The server is not on main, aborting."
        exit 1
    fi
    local old new
    old=$(git rev-parse --short HEAD)
    git fetch -q origin main
    git merge --ff-only -q origin/main
    new=$(git rev-parse --short HEAD)
    log "main $old -> $new"

    # Small servers have little memory, so the idle workers make room for the build and come back with the recreate.
    local workers=()
    read -ra workers <<< "$(compose config --services | grep -E '^celery-' | tr '\n' ' ')"
    log "Stopping the workers during the build: ${workers[*]}"
    compose stop "${workers[@]}"

    log "Building images while the site keeps running."
    local oom_before oom_after
    oom_before=$(dmesg 2>/dev/null | grep -c 'Out of memory' || true)
    if ! compose build; then
        log "Build failed, starting the workers again with the old version."
        compose start "${workers[@]}"
        exit 1
    fi
    oom_after=$(dmesg 2>/dev/null | grep -c 'Out of memory' || true)
    if [ "$oom_after" -gt "$oom_before" ]; then
        log "WARNING: the kernel killed $((oom_after - oom_before)) process(es) for lack of memory during the build."
    else
        log "No process was killed for lack of memory during the build."
    fi
    compose up -d --remove-orphans

    # Mounted source code only reaches a fresh container.
    local apps=()
    read -ra apps <<< "$(compose config --services | grep -E '^(backend|frontend|celery-.*)$' | tr '\n' ' ')"
    log "Recreating: ${apps[*]}"
    compose up -d --force-recreate --no-deps "${apps[@]}"
    proxy_reload

    docker image prune -f >/dev/null
    docker builder prune -f --keep-storage 8GB >/dev/null
    log "Free disk after cleanup: $(free_gb) GB"

    # With the bundled proxy the check goes through Caddy and its certificate, otherwise straight to the frontend.
    local url="http://127.0.0.1:3000/" host="" code=000
    if [ "$AUTO_HTTPS" = "true" ]; then
        host=$(env_get DOMAIN)
        host=${host%%,*}
        host=${host//[[:space:]]/}
        url="https://$host/"
    fi
    for _ in $(seq 1 36); do
        if [ -n "$host" ]; then
            code=$(curl -sk -o /dev/null -w '%{http_code}' --resolve "$host:443:127.0.0.1" "$url" || true)
        else
            code=$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)
        fi
        if [ "$code" = "200" ]; then
            log "$url answers 200, deploy of $new done."
            exit 0
        fi
        sleep 5
    done
    log "$url did not answer 200 within 3 min (last: $code)."
    exit 1
}

main "$@"
# Bash never reads past this line, even after git pull has changed the file.
# shellcheck disable=SC2317
exit
