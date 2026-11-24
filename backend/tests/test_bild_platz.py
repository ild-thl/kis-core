"""Every generated image needs a seat at the provider, else images pile up there.

Load test 26.09.: myLab paints one image at a time (11 s), 24 in parallel hit the 300 s limit and 92 of 110 images were missing.
"""

import base64

import httpx
import pytest

from src.features.praesentation import bild
from src.services import provider_slots, provider_transport as pt
from src.services.provider_slots import ProviderFull
from src.services.upstream_errors import is_upstream_busy
from src.tasks import general_tasks as gt

MYLAB = {"id": 21, "name": "myLab", "base_url": "https://models.mylab.example/v1", "api_key": "k",
         "enabled": True, "protocol": "openai_compat", "concurrency": {"image": 1}}


class _Redis:
    def __init__(self):
        self.sets = {}

    def zremrangebyscore(self, key, lo, hi):
        pass

    def zcard(self, key):
        return len(self.sets.get(key, {}))

    def zadd(self, key, mapping, nx=False, xx=False):
        s = self.sets.setdefault(key, {})
        for k, v in mapping.items():
            if not ((nx and k in s) or (xx and k not in s)):
                s[k] = v

    def zrem(self, key, *members):
        for m in members:
            self.sets.get(key, {}).pop(m, None)

    def zrank(self, key, member):
        s = self.sets.get(key, {})
        return sorted(s, key=lambda k: (s[k], k)).index(member) if member in s else None

    def zrangebyscore(self, key, lo, hi):
        return [k for k, v in self.sets.get(key, {}).items() if v <= hi]

    def exists(self, key):
        return 0


@pytest.fixture
def voll(monkeypatch):
    """The only image seat at myLab is taken, no waiting."""
    r = _Redis()
    r.zadd("askf:provider-slots:21:image", {"besetzt": 1.0})
    monkeypatch.setattr(provider_slots, "_redis", lambda: r)
    monkeypatch.setattr(pt, "_redis", lambda: r)
    monkeypatch.setattr(pt, "PROVIDER_SEAT_WAIT_SECONDS", 0)
    return r


def _mit_tuer(protokoll):
    def handler(req):
        protokoll.append("post")
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(b"png").decode()}]})
    tuer = pt.ProviderTransport(pt.Target.of(MYLAB, "flux"), None, "image", inner=httpx.MockTransport(handler))
    return lambda *a, **k: ("https://models.mylab.example/v1", "flux", httpx.Client(transport=tuer))


def test_der_bildclient_bekommt_die_tuer_mit_dem_feld_des_anbieters(monkeypatch):
    from src.services import feature_router
    monkeypatch.setattr(feature_router, "resolve",
                        lambda f: feature_router.FeatureBinding(feature=f, provider=MYLAB, model="flux"))
    monkeypatch.setattr(pt, "fallback_target", lambda *a, **k: None)
    _base, _model, client = gt._image_http_client("image_gen")
    assert client._transport._door.bucket == "image"
    assert client._transport._door.primary.caps == {"image": 1}


def test_ein_praesentationsbild_malt_mit_freiem_platz(monkeypatch):
    protokoll = []
    r = _Redis()
    monkeypatch.setattr(provider_slots, "_redis", lambda: r)
    monkeypatch.setattr(pt, "_redis", lambda: r)
    monkeypatch.setattr(bild, "_image_http_client", _mit_tuer(protokoll))

    assert bild.erzeuge("a lab", "1024x576") == b"png"
    assert protokoll == ["post"]
    assert r.zcard("askf:provider-slots:21:image") == 0


def test_ohne_platz_geht_keine_anfrage_raus(monkeypatch, voll):
    protokoll = []
    monkeypatch.setattr(bild, "_image_http_client", _mit_tuer(protokoll))

    with pytest.raises(ProviderFull):
        bild.erzeuge("a lab", "1024x576")
    assert protokoll == []


def test_der_bildauftrag_wartet_auf_denselben_platz(monkeypatch, voll):
    protokoll, gemeldet = [], []
    monkeypatch.setattr(gt.db, "update_job_status", lambda *a, **k: None)
    monkeypatch.setattr(gt, "_resolve_user_id", lambda j: 1)
    monkeypatch.setattr(gt, "_image_http_client", _mit_tuer(protokoll))
    monkeypatch.setattr(gt, "_handle_task_exception", lambda job, e, task_label: gemeldet.append(e))

    with pytest.raises(ProviderFull):
        gt.run_image_generate.run.__func__(None, "job1", "a cat", "1024x1024", None)
    assert protokoll == []
    # The busy wording makes the job wait instead of burning an attempt.
    assert isinstance(gemeldet[0], ProviderFull) and is_upstream_busy(gemeldet[0])
