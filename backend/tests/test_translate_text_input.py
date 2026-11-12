"""The /translate route accepts pasted text as an alternative to a file upload."""
import asyncio

import pytest
from fastapi import HTTPException


class _Request:
    headers: dict = {}


def _wire(monkeypatch, route):
    monkeypatch.setattr(route.db, "create_job", lambda *a, **k: None)
    monkeypatch.setattr(route.db, "set_job_input_path", lambda *a, **k: None)
    monkeypatch.setattr(route, "save_queue_file_from_path", lambda *a, **k: "users/1/jobs/x/input")
    monkeypatch.setattr(route, "enforce_tool_burst", lambda *a, **k: None)
    monkeypatch.setattr(route, "enforce_quota", lambda *a, **k: None)
    monkeypatch.setattr(route, "is_admin_user", lambda u: False)

    import src.tasks.general_tasks as gt
    captured = {}

    def fake_apply_async(args=None, **kwargs):
        captured["filename"] = args[2]
        return type("R", (), {"id": "task-1"})()

    monkeypatch.setattr(gt, "run_translate", type("T", (), {"apply_async": staticmethod(fake_apply_async)})())
    monkeypatch.setattr(route.db, "set_job_celery_task_id", lambda *a, **k: None)
    return captured


def test_text_input_queues_job_as_txt(monkeypatch):
    from src.routes import translate as route
    captured = _wire(monkeypatch, route)

    asyncio.run(route.translate(
        request=_Request(), file=None, text="Ein Satz zum Uebersetzen.",
        glossary="", provider_id=None, source_lang="", target_lang="",
        current_user={"user_id": 1}, locale="de",
    ))

    assert captured["filename"] == "text.txt"


def test_both_file_and_text_is_rejected(monkeypatch):
    from src.routes import translate as route
    _wire(monkeypatch, route)

    class _Upload:
        filename = "doc.txt"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(route.translate(
            request=_Request(), file=_Upload(), text="Text",
            glossary="", provider_id=None, source_lang="", target_lang="",
            current_user={"user_id": 1}, locale="de",
        ))
    assert exc.value.status_code == 400


def test_neither_file_nor_text_is_rejected(monkeypatch):
    from src.routes import translate as route
    _wire(monkeypatch, route)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(route.translate(
            request=_Request(), file=None, text="",
            glossary="", provider_id=None, source_lang="", target_lang="",
            current_user={"user_id": 1}, locale="de",
        ))
    assert exc.value.status_code == 400


def test_text_over_limit_is_rejected(monkeypatch):
    from src.routes import translate as route
    _wire(monkeypatch, route)
    monkeypatch.setattr(route, "TRANSLATE_MAX_CHARS", 10)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(route.translate(
            request=_Request(), file=None, text="x" * 20,
            glossary="", provider_id=None, source_lang="", target_lang="",
            current_user={"user_id": 1}, locale="de",
        ))
    assert exc.value.status_code == 422


def _upload(name: str, data: bytes):
    import io
    from starlette.datastructures import UploadFile
    return UploadFile(file=io.BytesIO(data), filename=name)


def test_latin1_tex_upload_is_accepted(monkeypatch):
    from src.routes import translate as route
    captured = _wire(monkeypatch, route)
    data = "\\usepackage[latin1]{inputenc}\nGrüße aus der Vorlesung.".encode("cp1252")

    asyncio.run(route.translate(
        request=_Request(), file=_upload("skript.tex", data), text=None,
        glossary="", provider_id=None, source_lang="", target_lang="",
        current_user={"user_id": 1}, locale="de",
    ))

    assert captured["filename"] == "skript.tex"


def test_binary_tex_upload_is_rejected(monkeypatch):
    from src.routes import translate as route
    _wire(monkeypatch, route)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(route.translate(
            request=_Request(), file=_upload("skript.tex", b"\x00\x01\x02 binary"), text=None,
            glossary="", provider_id=None, source_lang="", target_lang="",
            current_user={"user_id": 1}, locale="de",
        ))
    assert exc.value.status_code == 400


def test_tex_length_counts_text_the_extractor_would_drop(monkeypatch):
    from src.routes import translate as route
    _wire(monkeypatch, route)
    monkeypatch.setattr(route, "TRANSLATE_MAX_CHARS", 20)
    data = b"\\begin{document}$x \\text{ein langer Text in einer Formel}$\\end{document}"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(route.translate(
            request=_Request(), file=_upload("skript.tex", data), text=None,
            glossary="", provider_id=None, source_lang="", target_lang="",
            current_user={"user_id": 1}, locale="de",
        ))
    assert exc.value.status_code == 422
