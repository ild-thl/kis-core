"""Provider slots: never more concurrent requests than it can take, the rest wait on our side."""

import pytest

from src.services import provider_slots


class _Redis:
    """A sorted set like in Redis, with an adjustable clock."""

    def __init__(self):
        self.sets: dict[str, dict[str, float]] = {}

    def zremrangebyscore(self, key, lo, hi):
        s = self.sets.setdefault(key, {})
        for k in [k for k, v in s.items() if v <= hi]:
            del s[k]

    def zcard(self, key):
        return len(self.sets.get(key, {}))

    def zadd(self, key, mapping):
        self.sets.setdefault(key, {}).update(mapping)

    def zrem(self, key, member):
        self.sets.get(key, {}).pop(member, None)


@pytest.fixture
def uhr(monkeypatch):
    stand = {"t": 1000.0}
    monkeypatch.setattr(provider_slots.time, "time", lambda: stand["t"])

    def schlafen(sek):
        stand["t"] += sek

    monkeypatch.setattr(provider_slots.time, "sleep", schlafen)
    return stand


def test_bis_zur_grenze_gibt_es_sofort_einen_platz(uhr):
    r = _Redis()
    for _ in range(4):
        assert provider_slots.claim("mylab", limit=4, wait_seconds=0, r=r)
    assert r.zcard("askf:provider-slots:mylab") == 4


def test_ueber_der_grenze_wartet_die_anfrage_und_gibt_dann_als_voll_auf(uhr):
    """Load test 26.09.: from 12 concurrent voicings every single one failed at myLab."""
    r = _Redis()
    for _ in range(4):
        provider_slots.claim("mylab", limit=4, wait_seconds=0, r=r)
    start = uhr["t"]
    with pytest.raises(provider_slots.ProviderFull) as fehler:
        provider_slots.claim("mylab", limit=4, wait_seconds=30, r=r)
    assert uhr["t"] - start >= 30
    # The message must be recognized as "provider full", else it counts as a failed attempt.
    from src.services.upstream_errors import is_upstream_busy
    assert is_upstream_busy(fehler.value)


def test_ein_freigegebener_platz_geht_an_den_naechsten(uhr):
    r = _Redis()
    tickets = [provider_slots.claim("mylab", limit=2, wait_seconds=0, r=r) for _ in range(2)]
    provider_slots.release("mylab", tickets[0], r=r)
    assert provider_slots.claim("mylab", limit=2, wait_seconds=0, r=r)


def test_ein_verwaister_platz_heilt_von_selbst(uhr):
    """If a worker dies mid-request, its slot must not stay taken forever."""
    r = _Redis()
    for _ in range(2):
        provider_slots.claim("mylab", limit=2, wait_seconds=0, r=r)
    uhr["t"] += provider_slots.STALE_SECONDS + 1
    assert provider_slots.claim("mylab", limit=2, wait_seconds=0, r=r)


def test_anbieter_zaehlen_getrennt(uhr):
    r = _Redis()
    provider_slots.claim("a", limit=1, wait_seconds=0, r=r)
    assert provider_slots.claim("b", limit=1, wait_seconds=0, r=r)


def test_ohne_redis_laeuft_die_anfrage_durch(uhr):
    class _Kaputt:
        def zremrangebyscore(self, *a):
            raise ConnectionError("weg")

    assert provider_slots.claim("mylab", limit=1, wait_seconds=0, r=_Kaputt())


def test_der_platz_wird_auch_bei_einem_fehler_zurueckgegeben(uhr):
    r = _Redis()
    with pytest.raises(RuntimeError):
        with provider_slots.slot("mylab", limit=1, wait_seconds=0, r=r):
            raise RuntimeError("Anbieter antwortet 500")
    assert r.zcard("askf:provider-slots:mylab") == 0


def test_eine_zeitgrenze_beim_warten_laesst_die_anfrage_nicht_ohne_platz_durch(uhr, monkeypatch):
    """Celery's soft time limit is an exception too, it must not count as a Redis outage."""
    from celery.exceptions import SoftTimeLimitExceeded

    r = _Redis()
    provider_slots.claim("mylab", limit=1, wait_seconds=0, r=r)

    def grenze(sek):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(provider_slots.time, "sleep", grenze)
    with pytest.raises(SoftTimeLimitExceeded):
        provider_slots.claim("mylab", limit=1, wait_seconds=60, r=r)
    assert r.zcard("askf:provider-slots:mylab") == 1


# ─── Order at the door ────────────────────────────────────────────────


class _RangRedis(_Redis):
    """Plus the waiting queue at the door, sorted like in Redis."""

    def zadd(self, key, mapping, nx=False, xx=False):
        s = self.sets.setdefault(key, {})
        for k, v in mapping.items():
            if (nx and k in s) or (xx and k not in s):
                continue
            s[k] = v

    def zrank(self, key, member):
        s = self.sets.get(key, {})
        if member not in s:
            return None
        return sorted(s, key=lambda k: (s[k], k)).index(member)

    def zrangebyscore(self, key, lo, hi):
        return [k for k, v in self.sets.get(key, {}).items() if v <= hi]

    def zrem(self, key, *members):
        for m in members:
            self.sets.get(key, {}).pop(m, None)


def test_eine_niedrigere_stufe_kommt_zuerst_dran(uhr):
    """A short translation snippet should not wait behind a summary."""
    r = _RangRedis()
    provider_slots.claim_ranked("mylab:llm", limit=1, wait_seconds=0, rank=0, r=r)
    uhr["t"] += 1
    assert not provider_slots._try_sit_ranked(r, "mylab:llm", "lang", 1, 900, 2)
    uhr["t"] += 1
    assert not provider_slots._try_sit_ranked(r, "mylab:llm", "kurz", 1, 900, 0)
    r.sets["askf:provider-slots:mylab:llm"].clear()
    assert not provider_slots._try_sit_ranked(r, "mylab:llm", "lang", 1, 900, 2)
    assert provider_slots._try_sit_ranked(r, "mylab:llm", "kurz", 1, 900, 0)


def test_in_derselben_stufe_gilt_wer_zuerst_kam(uhr):
    r = _RangRedis()
    provider_slots.claim_ranked("mylab:llm", limit=1, wait_seconds=0, rank=1, r=r)
    assert not provider_slots._try_sit_ranked(r, "mylab:llm", "erster", 1, 900, 1)
    uhr["t"] += 1
    assert not provider_slots._try_sit_ranked(r, "mylab:llm", "zweiter", 1, 900, 1)
    r.sets["askf:provider-slots:mylab:llm"].clear()
    assert not provider_slots._try_sit_ranked(r, "mylab:llm", "zweiter", 1, 900, 1)
    assert provider_slots._try_sit_ranked(r, "mylab:llm", "erster", 1, 900, 1)


def test_wer_nicht_mehr_fragt_verlaesst_die_schlange(uhr):
    """A worker that died while waiting must not block the queue forever."""
    r = _RangRedis()
    provider_slots.claim_ranked("mylab:llm", limit=1, wait_seconds=0, rank=0, r=r)
    assert not provider_slots._try_sit_ranked(r, "mylab:llm", "tot", 1, 900, 0)
    r.sets["askf:provider-slots:mylab:llm"].clear()
    uhr["t"] += 60
    assert provider_slots._try_sit_ranked(r, "mylab:llm", "lebt", 1, 900, 0)


def test_wer_aufgibt_raeumt_seinen_platz_in_der_schlange(uhr):
    r = _RangRedis()
    provider_slots.claim_ranked("mylab:llm", limit=1, wait_seconds=0, rank=0, r=r)
    with pytest.raises(provider_slots.ProviderFull):
        provider_slots.claim_ranked("mylab:llm", limit=1, wait_seconds=5, rank=2, r=r)
    assert r.zcard("askf:provider-wait:mylab:llm") == 0


def test_die_asynchrone_tuer_haelt_dieselbe_reihenfolge(uhr, monkeypatch):
    import asyncio

    async def schlafen(sek):
        uhr["t"] += sek

    monkeypatch.setattr(asyncio, "sleep", schlafen)
    r = _RangRedis()
    asyncio.run(provider_slots.claim_ranked_async("mylab:llm", limit=1, wait_seconds=0, rank=0, r=r))
    with pytest.raises(provider_slots.ProviderFull):
        asyncio.run(provider_slots.claim_ranked_async("mylab:llm", limit=1, wait_seconds=5, rank=2, r=r))
    assert r.zcard("askf:provider-wait:mylab:llm") == 0


# ─── Keeping fresh ────────────────────────────────────────────────────────


def test_ein_gehaltener_platz_wird_erneuert_und_ein_freigegebener_nicht(uhr, monkeypatch):
    """After a restart slots stayed taken for 15 minutes, now only until nobody renews them."""
    r = _RangRedis()
    monkeypatch.setattr(provider_slots, "_redis", lambda: r)
    monkeypatch.setattr(provider_slots, "_start_refresher", lambda: None)
    gehalten = provider_slots.claim_ranked("mylab:llm", limit=5, wait_seconds=0, rank=0)
    frei = provider_slots.claim_ranked("mylab:llm", limit=5, wait_seconds=0, rank=0)
    provider_slots.release("mylab:llm", frei)
    uhr["t"] += 60
    provider_slots._refresh_once()
    assert r.sets["askf:provider-slots:mylab:llm"] == {gehalten: uhr["t"]}
    provider_slots.release("mylab:llm", gehalten)


def test_der_platz_eines_toten_prozesses_wird_nach_kurzer_zeit_frei(uhr, monkeypatch):
    r = _RangRedis()
    monkeypatch.setattr(provider_slots, "_redis", lambda: r)
    monkeypatch.setattr(provider_slots, "_start_refresher", lambda: None)
    r.zadd("askf:provider-slots:mylab:llm", {"tot": uhr["t"]})
    uhr["t"] += provider_slots.HELD_STALE_SECONDS + 1
    assert provider_slots.claim_ranked("mylab:llm", limit=1, wait_seconds=0, rank=0,
                                       stale_seconds=provider_slots.HELD_STALE_SECONDS)


def test_ein_abbruch_zwischen_hinsetzen_und_zaehlen_laesst_keinen_platz_besetzt(uhr):
    """A time limit right after sitting down left a seat nobody held and nobody gave back."""
    from celery.exceptions import SoftTimeLimitExceeded

    class _Bricht(_RangRedis):
        gezaehlt = 0

        def zcard(self, key):
            self.gezaehlt += 1
            if self.gezaehlt == 2:
                raise SoftTimeLimitExceeded()
            return super().zcard(key)

    r = _Bricht()
    with pytest.raises(SoftTimeLimitExceeded):
        provider_slots.claim_ranked("mylab:llm", limit=1, wait_seconds=0, rank=0, r=r)
    assert r.zcard("askf:provider-slots:mylab:llm") == 0
    assert r.zcard("askf:provider-wait:mylab:llm") == 0


def test_ein_abgebrochenes_asynchrones_warten_verlaesst_die_schlange(uhr, monkeypatch):
    import asyncio

    async def abbruch(sek):
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", abbruch)
    r = _RangRedis()
    r.zadd("askf:provider-slots:mylab:llm", {"besetzt": uhr["t"]})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider_slots.claim_ranked_async("mylab:llm", limit=1, wait_seconds=60, rank=0, r=r))
    assert r.zcard("askf:provider-wait:mylab:llm") == 0
    assert r.zcard("askf:provider-seen:mylab:llm") == 0
