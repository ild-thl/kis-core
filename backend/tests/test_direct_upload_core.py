"""One core for direct uploads: parts go to the bucket, complete checks them, tools take the file."""
import asyncio

import pytest
from fastapi import HTTPException

import src.routes.transcription  # noqa: F401 - registers the transcription rule
from src.routes import _shared
from src.routes import uploads as routes
from src.services import direct_upload as du

PART = du.PART_SIZE
MP3_HEAD = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
RULE = du.UploadRule({".mp3"}, lambda: 500 * 1024 * 1024)


class _FakeRedis:
    def __init__(self, store):
        self._store = store

    def set(self, key, value, ex=None):
        self._store[key] = value

    def get(self, key):
        return self._store.get(key)

    def delete(self, key):
        self._store.pop(key, None)

    def pipeline(self, transaction=True):
        store, ops = self._store, []

        class _Pipe:
            def get(self, key):
                ops.append(("get", key))

            def delete(self, key):
                ops.append(("delete", key))

            def execute(self):
                out = []
                for op, key in ops:
                    out.append(store.get(key) if op == "get" else int(store.pop(key, None) is not None))
                return out
        return _Pipe()


@pytest.fixture
def bucket(monkeypatch):
    """Bucket and Redis stubbed, every call recorded."""
    state = {"redis": {}, "parts": [], "deleted": [], "aborted": [], "completed": [], "cors": [],
             "head": MP3_HEAD, "started": []}
    monkeypatch.setattr(du, "USE_S3", True)
    monkeypatch.setattr(du, "_redis", lambda: _FakeRedis(state["redis"]))
    monkeypatch.setattr(du, "ensure_upload_cors", lambda origin: state["cors"].append(origin))
    monkeypatch.setattr(du, "multipart_start", lambda key, ct: state["started"].append(key) or "up-1")
    monkeypatch.setattr(du, "multipart_part_url", lambda key, uid, n, sec, length: state.setdefault("signed", []).append((n, length)) or f"https://bucket/{key}?part={n}")
    monkeypatch.setattr(du, "multipart_parts", lambda key, uid: state["parts"])
    monkeypatch.setattr(du, "multipart_complete", lambda key, uid, parts: state["completed"].append(parts))
    monkeypatch.setattr(du, "multipart_abort", lambda key, uid: state["aborted"].append(key))
    monkeypatch.setattr(du, "get_range", lambda key, start, length: state["head"])
    monkeypatch.setattr(du, "delete_file", lambda key: state["deleted"].append(key))
    return state


def _start(name="vortrag.mp3", size=PART * 2 + 5, user_id=42, rule=RULE, tool="transcription"):
    return du.start(tool, rule, name, size, user_id, {}, "https://kis.example", "kis.example", "de")


def _parts(numbers, size):
    count = du.part_count(size)
    return [{"PartNumber": n, "ETag": f"e{n}", "Size": PART if n < count else size - PART * (count - 1)}
            for n in numbers]


def _finished(bucket, **kw):
    token = _start(**kw)["token"]
    bucket["parts"] = _parts([1, 2, 3], PART * 2 + 5)
    du.complete(token, kw.get("user_id", 42), "de")
    return token


# --- pure helpers ---------------------------------------------------------------

def test_teilezahl_rundet_auf_und_leere_datei_hat_einen_teil():
    assert du.part_count(1) == 1
    assert du.part_count(PART) == 1
    assert du.part_count(PART + 1) == 2
    assert du.part_count(0) == 1


def test_nur_vollstaendige_teile_zaehlen_als_fertig():
    size = PART * 2 + 5
    parts = _parts([1, 2, 3], size)
    parts[1]["Size"] = PART - 10
    assert du.done_parts(parts, size) == [1, 3]


def test_teile_muessen_lueckenlos_und_in_der_summe_passen():
    size = PART * 2 + 5
    assert du.parts_complete(_parts([1, 2, 3], size), size)
    assert not du.parts_complete(_parts([1, 3], size), size)
    assert not du.parts_complete(_parts([1, 2, 3], size + 1), size)


def test_same_site_origin_nur_bei_gleichem_host():
    assert du.same_site_origin("https://kis.example", "kis.example") == "https://kis.example"
    assert du.same_site_origin("https://evil.example", "kis.example") == ""
    assert du.same_site_origin("", "kis.example") == ""


def test_teilgroesse_voll_bis_auf_den_letzten():
    size = PART * 2 + 5
    assert [du.part_length(n, size) for n in (1, 2, 3)] == [PART, PART, 5]


def test_endung_ist_klein_und_mit_punkt():
    assert du.extension_of("Vortrag.MP3") == ".mp3"
    assert du.extension_of("ohne") == ""


# --- start ----------------------------------------------------------------------

def test_start_legt_die_datei_im_zwischenordner_ab(bucket):
    answer = _start()
    assert answer["direct"] is True and answer["part_size"] == PART and answer["part_count"] == 3
    assert bucket["started"] == [f"tmp/uploads/42/{answer['token']}.mp3"]
    assert bucket["cors"] == ["https://kis.example"]


def test_start_ohne_s3_oder_fremde_endung_nimmt_den_klassischen_weg(bucket, monkeypatch):
    assert _start(name="notiz.txt") == {"direct": False}
    monkeypatch.setattr(du, "USE_S3", False)
    assert _start() == {"direct": False}


def test_start_lehnt_leere_und_zu_grosse_dateien_ab(bucket):
    with pytest.raises(HTTPException) as empty:
        _start(size=0)
    assert empty.value.status_code == 400
    small = du.UploadRule({".mp3"}, lambda: 32 * 1024 * 1024)
    with pytest.raises(HTTPException) as big:
        _start(size=33 * 1024 * 1024, rule=small)
    assert big.value.status_code == 413


# --- status, urls, abort --------------------------------------------------------

def test_status_nennt_nur_vollstaendige_teile(bucket):
    token = _start()["token"]
    bucket["parts"] = _parts([1, 2], PART * 2 + 5)
    bucket["parts"][1]["Size"] = 10
    assert du.status(token, 42, "de")["uploaded"] == [1]


def test_status_eines_verschwundenen_uploads_ist_404(bucket, monkeypatch):
    token = _start()["token"]
    monkeypatch.setattr(du, "multipart_parts", lambda key, uid: None)
    with pytest.raises(HTTPException) as err:
        du.status(token, 42, "de")
    assert err.value.status_code == 404


def test_urls_werden_pro_teil_signiert_und_falsche_nummern_abgelehnt(bucket):
    token = _start()["token"]
    assert set(du.urls(token, [1, 3], 42, "de")["urls"]) == {"1", "3"}
    # The exact size of each part is signed, the bucket refuses anything else.
    assert bucket["signed"] == [(1, PART), (3, 5)]
    for bad in ([0], [4]):
        with pytest.raises(HTTPException) as err:
            du.urls(token, bad, 42, "de")
        assert err.value.status_code == 400


def test_fremde_person_sieht_den_upload_nicht(bucket):
    token = _start()["token"]
    with pytest.raises(HTTPException) as err:
        du.status(token, 99, "de")
    assert err.value.status_code == 404


def test_abbruch_verwirft_teile_oder_fertige_datei(bucket):
    token = _start()["token"]
    du.abort(token, 42, "de")
    assert len(bucket["aborted"]) == 1
    done = _finished(bucket)
    du.abort(done, 42, "de")
    assert len(bucket["deleted"]) == 1
    with pytest.raises(HTTPException):
        du.load(done, 42, "de")


# --- complete -------------------------------------------------------------------

def test_abschluss_fuegt_zusammen_prueft_und_ist_wiederholbar(bucket):
    token = _start()["token"]
    bucket["parts"] = _parts([1, 2, 3], PART * 2 + 5)
    first = du.complete(token, 42, "de")
    assert first["done"] is True and first["filename"] == "vortrag.mp3"
    assert [p["PartNumber"] for p in bucket["completed"][0]] == [1, 2, 3]
    # A second call after a lost answer changes nothing and joins nothing again.
    assert du.complete(token, 42, "de")["done"] is True
    assert len(bucket["completed"]) == 1


def test_abschluss_mit_fehlenden_teilen_ist_409_und_bleibt_offen(bucket):
    token = _start()["token"]
    bucket["parts"] = _parts([1, 3], PART * 2 + 5)
    with pytest.raises(HTTPException) as err:
        du.complete(token, 42, "de")
    assert err.value.status_code == 409
    assert bucket["completed"] == []
    assert du.load(token, 42, "de")["done"] is False


def test_abschluss_mit_falscher_summe_ist_409(bucket):
    token = _start()["token"]
    bucket["parts"] = _parts([1, 2, 3], PART * 2 + 5)
    bucket["parts"][2]["Size"] += 1
    with pytest.raises(HTTPException) as err:
        du.complete(token, 42, "de")
    assert err.value.status_code == 409


def test_abschluss_loescht_eine_datei_die_nicht_zur_endung_passt(bucket):
    token = _start()["token"]
    bucket["parts"] = _parts([1, 2, 3], PART * 2 + 5)
    bucket["head"] = b"MZ\x90\x00" + b"\x00" * 64
    with pytest.raises(HTTPException):
        du.complete(token, 42, "de")
    assert len(bucket["deleted"]) == 1
    with pytest.raises(HTTPException):
        du.load(token, 42, "de")


# --- take and release -----------------------------------------------------------

def test_werkzeug_bekommt_nur_fertige_uploads_fuer_sich(bucket):
    open_token = _start()["token"]
    with pytest.raises(HTTPException):
        du.take(open_token, "transcription", 42, "de")
    token = _finished(bucket)
    assert du.take(token, "transcription", 42, "de")["filename"] == "vortrag.mp3"
    assert du.take(token, {"translate", "transcription"}, 42, "de")
    with pytest.raises(HTTPException):
        du.take(token, "translate", 42, "de")
    with pytest.raises(HTTPException):
        du.take(token, "transcription", 99, "de")


def test_freigeben_loescht_datei_und_sitzung(bucket):
    token = _finished(bucket)
    session = du.take(token, "transcription", 42, "de")
    du.release(token, session)
    assert bucket["deleted"] == [session["key"]]
    with pytest.raises(HTTPException):
        du.load(token, 42, "de")


# --- stage_input, the one way every tool route receives a file ------------------

def test_stage_input_holt_die_datei_aus_dem_speicher(bucket, monkeypatch, tmp_path):
    token = _finished(bucket)
    payload = MP3_HEAD + b"x" * 100
    monkeypatch.setattr("src.storage.download_to_path", lambda key, path: open(path, "wb").write(payload))
    dest = tmp_path / "input.mp3"
    size, head = asyncio.run(_shared.stage_input(None, token, "transcription", 42, str(dest), 10**9, "de"))
    assert size == PART * 2 + 5
    assert head == payload
    assert dest.read_bytes() == payload
    # The file is now local, the staged copy is gone.
    assert len(bucket["deleted"]) == 1


def test_stage_input_haelt_die_grenze_ein(bucket, monkeypatch, tmp_path):
    token = _finished(bucket)
    monkeypatch.setattr("src.storage.download_to_path", lambda key, path: None)
    with pytest.raises(HTTPException) as err:
        asyncio.run(_shared.stage_input(None, token, "transcription", 42, str(tmp_path / "x"), 1024, "de"))
    assert err.value.status_code == 413


def test_name_kommt_aus_dem_upload(bucket):
    token = _finished(bucket)
    assert _shared.input_name(None, token, "transcription", 42, "de") == "vortrag.mp3"


# --- the rules table ------------------------------------------------------------

def test_unbekanntes_werkzeug_ist_verboten():
    with pytest.raises(HTTPException) as err:
        routes.rule_for("gibt-es-nicht", "de")
    assert err.value.status_code == 403


def test_transkription_hat_eine_regel():
    rule = routes.rule_for("transcription", "de")
    assert ".mp3" in rule.extensions


def test_ein_token_wird_nur_einmal_vergeben(bucket):
    token = _finished(bucket)
    session = du.claim(token, "transcription", 42, "de")
    assert session["filename"] == "vortrag.mp3"
    with pytest.raises(HTTPException) as err:
        du.claim(token, "transcription", 42, "de")
    assert err.value.status_code == 404
    # Put back after a refusal, the person can try again.
    du.unclaim(token, session)
    assert du.claim(token, "transcription", 42, "de")
