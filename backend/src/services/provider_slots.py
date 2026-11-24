"""Seats at a provider, shared by every worker, so requests wait with us instead of failing there."""

from __future__ import annotations

import asyncio
import os
import random
import threading
import time
import uuid
from contextlib import contextmanager

from loguru import logger
from src.core.redis_url import REDIS_URL

_KEY = "askf:provider-slots:{}"

# A seat older than this belongs to a worker that died mid request and is freed.
STALE_SECONDS = 5 * 60


try:
    from redis.exceptions import RedisError as _RedisError
except ImportError:  # pragma: no cover - redis is always installed in the containers
    _RedisError = OSError
# Only these mean Redis is gone, a time limit hitting while we wait must not open the door.
_REDIS_DOWN = (_RedisError, OSError)


class ProviderFull(RuntimeError):
    """No seat came free in time, worded so that it counts as a full provider (503)."""

    def __init__(self, provider: str, waited: float):
        super().__init__(f"503 service unavailable: provider {provider} full, waited {waited:.0f}s")
        self.provider, self.waited = provider, waited


def _redis():
    import redis as _redis_lib
    return _redis_lib.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=2)


def _try_sit(r, key: str, ticket: str, limit: int, stale_seconds: float) -> bool:
    """Sits down first and counts afterwards, so two workers can never both slip past the limit."""
    now = time.time()
    r.zremrangebyscore(key, "-inf", now - stale_seconds)
    r.zadd(key, {ticket: now})
    if r.zcard(key) <= limit:
        return True
    r.zrem(key, ticket)
    return False


def claim(provider: str, *, limit: int, wait_seconds: float, r=None,
          stale_seconds: float = STALE_SECONDS) -> str:
    """Takes a seat, waiting up to wait_seconds, and raises ProviderFull when none came free."""
    ticket = uuid.uuid4().hex
    key = _KEY.format(provider)
    start = time.time()
    try:
        r = r if r is not None else _redis()
        while not _try_sit(r, key, ticket, limit, stale_seconds):
            if time.time() - start >= wait_seconds:
                raise ProviderFull(provider, time.time() - start)
            time.sleep(0.5 + random.random())
        return ticket
    except _REDIS_DOWN as e:
        # Without Redis the request goes through unbraked.
        logger.warning("Anbieter-Plätze nicht erreichbar (Redis), lasse durch: {}", e)
        return ticket


# Seats this process holds right now, renewed so that only the seat of a dead process goes stale.
HELD_STALE_SECONDS = 90
_REFRESH_SECONDS = 20
_held: dict[str, str] = {}
_held_lock = threading.Lock()
_refresher_pid: int | None = None


def _refresh_once() -> None:
    """Stamps every seat this process still holds with the current time."""
    with _held_lock:
        held = list(_held.items())
    if not held:
        return
    try:
        r = _redis()
        now = time.time()
        for ticket, provider in held:
            r.zadd(_KEY.format(provider), {ticket: now}, xx=True)
    except _REDIS_DOWN as e:
        logger.warning("Anbieter-Plätze nicht erneuert: {}", e)


def _refresh_forever() -> None:
    pause = threading.Event()
    while not pause.wait(_REFRESH_SECONDS):
        _refresh_once()


def _start_refresher() -> None:
    """One renewing thread per process, a forked worker starts its own."""
    global _refresher_pid
    if _refresher_pid != os.getpid():
        _refresher_pid = os.getpid()
        threading.Thread(target=_refresh_forever, daemon=True, name="provider-seats").start()


def _hold(provider: str, ticket: str) -> None:
    with _held_lock:
        _held[ticket] = provider
    _start_refresher()


# The line in front of a provider, ordered by rank first and arrival second.
_WAIT_KEY = "askf:provider-wait:{}"
_SEEN_KEY = "askf:provider-seen:{}"
# A waiter asks again at least every 1.5 s, one that stayed silent this long has died.
WAITER_STALE_SECONDS = 30.0
# Keeps every rank apart from the next, the arrival time sorts within one rank.
_RANK_SPAN = 1e10


def _try_sit_ranked(r, provider: str, ticket: str, limit: int, stale_seconds: float, rank: int) -> bool:
    """Queues up once and sits down only when every free seat is not wanted by someone ahead."""
    key, wait, seen = _KEY.format(provider), _WAIT_KEY.format(provider), _SEEN_KEY.format(provider)
    now = time.time()
    r.zremrangebyscore(key, "-inf", now - stale_seconds)
    gone = r.zrangebyscore(seen, "-inf", now - WAITER_STALE_SECONDS)
    if gone:
        r.zrem(wait, *gone)
        r.zrem(seen, *gone)
    r.zadd(wait, {ticket: rank * _RANK_SPAN + now}, nx=True)
    r.zadd(seen, {ticket: now})
    free = limit - r.zcard(key)
    position = r.zrank(wait, ticket)
    if free <= 0 or position is None or position >= free:
        return False
    # Sit down first, then count, so two workers can never both slip past the limit.
    r.zadd(key, {ticket: now})
    if r.zcard(key) > limit:
        r.zrem(key, ticket)
        return False
    r.zrem(wait, ticket)
    r.zrem(seen, ticket)
    return True


def _leave_line(r, provider: str, ticket: str) -> None:
    """Takes a ticket that got no seat out of the line, and out of the seats a broken try left it in."""
    try:
        r.zrem(_WAIT_KEY.format(provider), ticket)
        r.zrem(_SEEN_KEY.format(provider), ticket)
        r.zrem(_KEY.format(provider), ticket)
    except _REDIS_DOWN:
        pass


def _ranked_waits(provider: str, *, limit: int, wait_seconds: float, rank: int, r,
                  stale_seconds: float):
    """Yields once per pause until the ticket sits and returns it, so both claims share all but the sleep."""
    ticket = uuid.uuid4().hex
    start = time.time()
    seated = False
    try:
        r = r if r is not None else _redis()
        while not _try_sit_ranked(r, provider, ticket, limit, stale_seconds, rank):
            if time.time() - start >= wait_seconds:
                raise ProviderFull(provider, time.time() - start)
            yield 0.5 + random.random()
        seated = True
        _hold(provider, ticket)
        return ticket
    except _REDIS_DOWN as e:
        seated = True
        # Without Redis the request goes through unbraked.
        logger.warning("Anbieter-Plätze nicht erreichbar (Redis), lasse durch: {}", e)
        return ticket
    finally:
        if not seated and r is not None:
            _leave_line(r, provider, ticket)


def claim_ranked(provider: str, *, limit: int, wait_seconds: float, rank: int, r=None,
                 stale_seconds: float = STALE_SECONDS) -> str:
    """Like claim, but lower ranks get the next free seat first and equal ranks in arrival order."""
    waits = _ranked_waits(provider, limit=limit, wait_seconds=wait_seconds, rank=rank, r=r,
                          stale_seconds=stale_seconds)
    try:
        while True:
            time.sleep(next(waits))
    except StopIteration as seated:
        return seated.value
    finally:
        # A time limit struck during the sleep, closing takes the ticket out of the line.
        waits.close()


async def claim_ranked_async(provider: str, *, limit: int, wait_seconds: float, rank: int, r=None,
                             stale_seconds: float = STALE_SECONDS) -> str:
    """Like claim_ranked, but waits without blocking the event loop."""
    waits = _ranked_waits(provider, limit=limit, wait_seconds=wait_seconds, rank=rank, r=r,
                          stale_seconds=stale_seconds)
    try:
        while True:
            await asyncio.sleep(next(waits))
    except StopIteration as seated:
        return seated.value
    finally:
        waits.close()


def release(provider: str, ticket: str, r=None) -> None:
    with _held_lock:
        _held.pop(ticket, None)
    try:
        (r if r is not None else _redis()).zrem(_KEY.format(provider), ticket)
    except Exception as e:  # noqa: BLE001 - the seat drops out by itself after STALE_SECONDS
        logger.warning("Anbieter-Platz nicht freigegeben: {}", e)


@contextmanager
def slot(provider: str, *, limit: int, wait_seconds: float, r=None):
    """A seat for the duration of one request, given back even when the request fails."""
    ticket = claim(provider, limit=limit, wait_seconds=wait_seconds, r=r)
    try:
        yield
    finally:
        release(provider, ticket, r=r)
