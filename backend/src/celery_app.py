import gc

from celery import Celery, Task
from celery.schedules import crontab
from celery.signals import (
    task_failure, task_prerun, task_revoked, worker_before_create_process, worker_process_init, worker_ready,
)
from loguru import logger
from src.core.redis_url import CELERY_RESULT_URL, REDIS_URL

# A task whose worker dies goes back in line (task_reject_on_worker_lost), but a task that
# kills its worker every time must not circle forever: after this many starts it gives up.
MAX_STARTS = 4
_START_KEY = "askf:task-starts:{}:{}"


def start_allowed(task_id: str, retries: int, r=None) -> bool:
    """Counts one start of this task and says whether it may still run."""
    try:
        if r is None:
            import redis as _redis_lib
            r = _redis_lib.from_url(REDIS_URL,
                                    socket_connect_timeout=1, socket_timeout=2)
        key = _START_KEY.format(task_id, retries)
        n = r.incr(key)
        r.expire(key, 24 * 3600)
        return n <= MAX_STARTS
    except Exception:  # noqa: BLE001 - without Redis the task simply runs
        return True


class _GuardedTask(Task):
    """Stops a task that already brought its worker down too often."""

    def __call__(self, *args, **kwargs):
        if self.request.id and not start_allowed(self.request.id, self.request.retries or 0):
            logger.error("Task {} {}: Arbeiter {}x abgestürzt, gebe auf", self.name, self.request.id, MAX_STARTS)
            reason = RuntimeError(f"Der Arbeiter ist bei diesem Auftrag {MAX_STARTS}-mal abgestürzt")
            _mark_aia_source_failed_from_signal(self, args, reason)
            _mark_task_failed(self.request.id, ("job.unexpectedError", {"error": str(reason)}))
            return None
        return super().__call__(*args, **kwargs)


celery_app = Celery(
    "askf",
    task_cls=_GuardedTask,
    broker=REDIS_URL,
    backend=CELERY_RESULT_URL,
    include=[
        "src.tasks.tts_tasks",
        "src.tasks.general_tasks",
        "src.tasks.summary_tasks",
        "src.tasks.screencast_tasks",
        "src.tasks.podcast_tasks",
        "src.tasks.praesentation_tasks",
        "src.tasks.pages_tasks",
        "src.tasks.watchdog_tasks",
        "src.tasks.cleanup_tasks",
        "src.tasks.backup_tasks",
        "src.tasks.aia_tasks",
        "src.tasks.campus_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=86400,  # 24h - matches file retention
    worker_max_tasks_per_child=10,  # restart worker every 10 tasks (prevent memory leaks)
    # A process still holding more than 400 MB after its task is replaced, one large document
    # must not keep memory that the 8 GB box needs elsewhere (in KiB).
    worker_max_memory_per_child=400_000,
    task_acks_late=True,  # only ack after task completes (no lost jobs on worker crash)
    # A worker killed for lack of memory puts its task back in line instead of failing it.
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # one task at a time per worker process
    # On a restart running tasks get 30 s, then their messages go straight back in line
    # instead of lying an hour with the broker as taken (docker-compose remaps TERM).
    worker_soft_shutdown_timeout=30.0,
    worker_enable_soft_shutdown_on_idle=True,
    task_routes={
        "tts.run": {"queue": "tts"},
        # Large texts and long recordings are sent to "long" by their route, see services/job_lanes.py.
        "general.translate": {"queue": "general"},
        "general.transcribe": {"queue": "general"},
        "general.image_generate": {"queue": "general"},
        "general.image_edit": {"queue": "general"},
        "general.image_analyze": {"queue": "general"},
        "screencast.translate": {"queue": "screencast"},
        "screencast.render": {"queue": "screencast"},
        # Work that holds a process for minutes has a worker of its own, so short services
        # never wait behind it (load test 2026-09-26: a 10 s transcript waited 12 minutes).
        "podcast.script": {"queue": "long"},
        # Holds a process 6 to 15 minutes under load, in general it kept transcripts waiting (run 15).
        "summary.run": {"queue": "long"},
        "pages.run": {"queue": "long"},
        # A picture or a language asked for in the editor is short work, the owner waits for it.
        "pages.image": {"queue": "general"},
        "pages.translate": {"queue": "general"},
        # The voicing waits on the voice provider and gets its own worker, so a busy provider
        # never holds up summaries and presentations.
        "podcast.render": {"queue": "tts"},
        "praesentation.outline": {"queue": "long"},
        "praesentation.build": {"queue": "long"},
        # A worker of its own, the supervisor must run even when every other slot is taken.
        "watchdog.check": {"queue": "control"},
        "cleanup.expired_files": {"queue": "general"},
        "cleanup.job_cap": {"queue": "general"},
        "cleanup.exercise_progress": {"queue": "general"},
        "backup.database": {"queue": "long"},
        # The campus crawl is long and rare, the chat cleanup is tiny.
        "campus.crawl": {"queue": "long"},
        "campus.index_document": {"queue": "long"},
        "cleanup.campus_chats": {"queue": "general"},
        # Sources get a queue of their own that the same worker takes turns with, never behind every tool.
        "aia.index_source": {"queue": "aia_ingest"},
        "aia.translate_transcript": {"queue": "aia_ingest"},
        "aia.reindex_all_sources": {"queue": "aia_ingest"},
        # AI tutor: dedicated queue for learning tools and language training
        "aia.generate_mindmap": {"queue": "aia"},
        "aia.generate_exercise_set": {"queue": "aia"},
        "aia.generate_data_table": {"queue": "aia"},
        "aia.generate_glossary": {"queue": "aia"},
    },
    beat_schedule={
        "watchdog-stuck-jobs": {
            "task": "watchdog.check",
            "schedule": 5.0,  # every 5 seconds
            # A tick that waited longer than this is dropped, the next one follows anyway.
            "options": {"queue": "control", "expires": 20},
        },
        # Runs exactly once here, no matter how many uvicorn processes exist.
        "cleanup-expired-files": {
            "task": "cleanup.expired_files",
            "schedule": 3600.0,  # stuendlich, wie vorher
            "options": {"queue": "general"},
        },
        # The job pool is the only retention rule.
        "cleanup-job-cap": {
            "task": "cleanup.job_cap",
            "schedule": 3600.0,  # stuendlich
            "options": {"queue": "general"},
        },
        # Locks accounts whose access-code deadline passed, never deletes them.
        "cleanup-lock-expired-access-accounts": {
            "task": "cleanup.lock_expired_access_accounts",
            "schedule": 3600.0,  # stuendlich
            "options": {"queue": "general"},
        },
        # A fixed time instead of an interval, so the backup runs at night.
        "backup-database": {
            "task": "backup.database",
            "schedule": crontab(hour=3, minute=30),
            "options": {"queue": "long"},
        },
        # After the backup, so what was deleted had been backed up.
        "cleanup-exercise-progress": {
            "task": "cleanup.exercise_progress",
            "schedule": crontab(hour=4, minute=15),
            "options": {"queue": "general"},
        },
        # Removes test accounts locked longer than the grace period, after the backup.
        "cleanup-delete-expired-access-accounts": {
            "task": "cleanup.delete_expired_access_accounts",
            "schedule": crontab(hour=4, minute=45),
            "options": {"queue": "general"},
        },
        # Campus pages are refreshed before the backup so the night backs up the fresh index.
        "campus-crawl": {
            "task": "campus.crawl",
            "schedule": crontab(hour=1, minute=30),
            "options": {"queue": "long"},
        },
        # Old campus chats go after the backup.
        "cleanup-campus-chats": {
            "task": "cleanup.campus_chats",
            "schedule": crontab(hour=4, minute=20),
            "options": {"queue": "general"},
        },
        # Spoken example sentences nobody has listened to for a long time.
        "cleanup-speech-cache": {
            "task": "cleanup.speech_cache",
            "schedule": crontab(hour=4, minute=30),
            "options": {"queue": "general"},
        },
    },
)


@worker_before_create_process.connect
def on_before_create_process(**kwargs):
    """Freezes the parent's objects before a fork, so a child shares them instead of copying them on its first garbage collection."""
    gc.freeze()


@worker_process_init.connect
def on_worker_process_init(**kwargs):
    """Every forked pool process opens its own database lines instead of sharing the parent's."""
    from src.core.db.pool import reset_after_fork
    reset_after_fork()


@task_prerun.connect
def on_task_prerun(task=None, **kwargs):
    """Queues every provider call of this job at the door by its lane, so quick services go first."""
    from src.services import provider_transport

    info = getattr(getattr(task, "request", None), "delivery_info", None) or {}
    provider_transport.set_seat_rank(provider_transport.seat_rank_for(info.get("routing_key"), info.get("priority")))
    provider_transport.set_seat_wait(provider_transport.seat_wait_for(info.get("routing_key")))


@worker_ready.connect
def on_worker_ready(**kwargs):
    """Clean up stale /tmp dirs left behind by SIGKILL'd tasks from a previous run."""
    import shutil
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.gettempdir())
    cleaned = 0
    for d in tmp.glob("tmp*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            cleaned += 1
    if cleaned:
        logger.info("Worker startup: removed {} stale temp dirs from {}", cleaned, tmp)


def _mark_task_failed(task_id: str, reason: str | tuple[str, dict]) -> None:
    """Counts one failed attempt for a running job, found via its Celery id."""
    try:
        from src import database as db
        from src.i18n import t
        from src.services import job_recovery
        job = db.get_job_by_celery_task_id(task_id)
        if not job:
            return
        locale = job.get("creator_locale") or "de"
        if isinstance(reason, tuple):
            key, params = reason
            message = t(key, locale, **params)
        elif isinstance(reason, str) and "." in reason and " " not in reason:
            message = t(reason, locale)
        else:
            message = reason
        status = job_recovery.attempt_failed(job["job_uuid"], message)
        logger.warning("Signal: job {} now {} - {}", job["job_uuid"][:8], status, message)
    except Exception as e:
        logger.error("Signal handler error: {}", e)


def _mark_aia_source_failed_from_signal(sender, args, exception) -> None:
    """Catches errors that arise at the function edge of aia.index_source."""
    if sender is None or sender.name != "aia.index_source":
        return
    if not args or not isinstance(args[0], str):
        return
    source_uuid = args[0]
    locale = args[1] if len(args) > 1 and isinstance(args[1], str) else "de"
    try:
        from src import database as db
        from src.i18n import t
        source = db.get_aia_source(source_uuid)
        if not source or source.get("status") == "failed":
            return
        message = t("job.unexpectedError", locale, error=str(exception))
        db.update_aia_source_status(source_uuid, "failed", error_message=message)
        logger.warning("Signal: aia_source {} marked failed - {}", source_uuid[:8], message)
    except Exception as e:
        logger.error("Signal handler (aia_source) error: {}", e)


@task_failure.connect
def on_task_failure(task_id, exception, **kwargs):
    _mark_aia_source_failed_from_signal(kwargs.get("sender"), kwargs.get("args") or (), exception)

    from celery.exceptions import SoftTimeLimitExceeded
    if isinstance(exception, SoftTimeLimitExceeded):
        # A friendly message instead of a raw exception if the deadline struck unguarded.
        _mark_task_failed(task_id, "job.timeoutRetry")
    else:
        _mark_task_failed(task_id, ("job.unexpectedError", {"error": str(exception)}))


@task_revoked.connect
def on_task_revoked(request, terminated, signum, expired, **kwargs):
    if terminated or expired:
        _mark_task_failed(request.id, "job.watchdogStuck")
