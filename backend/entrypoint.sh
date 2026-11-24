#!/bin/sh
# Starts askf-backend with one process per core minus one, at most 4.
#
# Several processes are only possible since everything shared left memory:
#   - session list in Redis          (services/session.py)
#   - upload brake in Redis          (features/ai_assistant/routes/sources/_upload.py)
#   - schema creation only once      (app.py, core/db/pool.py run_once_across_processes)
#   - job cleanup only on an empty broker (app.py _broker_was_emptied)
#   - hourly cleanup in celery-beat      (tasks/cleanup_tasks.py)
set -e

KERNE=$(nproc 2>/dev/null || echo 1)

# nproc counts the cores of the server, which holds while the compose file sets no cpu limits.
if [ "$KERNE" -gt 2 ]; then
    AUTO=$((KERNE - 1))   # ein Kern bleibt fuer Postgres, Redis und die Worker
else
    AUTO=1
fi
# Cap it. Every process costs about 300 MB and the container has 3 GB (mem_limit),
# beyond 4 more barely helps because the backend mostly waits on other services.
[ "$AUTO" -gt 4 ] && AUTO=4

WORKERS=$AUTO

echo "askf-backend: ${KERNE} core(s), starting ${WORKERS} process(es)"

# With one process start deliberately WITHOUT --workers. That is exactly the
# previous behaviour, without an extra supervisor process in front.
if [ "$WORKERS" -le 1 ]; then
    exec python -m uvicorn src.app:app --host 0.0.0.0 --port 8000
fi

# A process that stalls a few seconds under load (memory pressure, a long request) is not
# killed with every request it is serving: uvicorn's default of 5 seconds did exactly that.
exec python -m uvicorn src.app:app --host 0.0.0.0 --port 8000 --workers "$WORKERS" \
    --timeout-worker-healthcheck 30
