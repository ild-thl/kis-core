"""A shared page opens without a askFrancis account only when its owner opened the link to everyone."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

CODE = "zvprBBdCNCMgBvBz"
PAGE = {"version": 1, "lang": "de", "design": "chapters", "footer": "",
        "sections": [{"id": "top", "hero": True, "title": "Regression", "lead": "", "blocks": []}]}


def _row(public: bool) -> dict:
    return {"job_uuid": "a" * 32, "user_id": 7, "status": "success", "public": public,
            "owner_name": "f f", "collection_code": "wqH6UD7FJR3PSCgm"}


@pytest.fixture
def client_ohne_sitzung():
    """The gate stays armed, this is what proves the open prefix."""
    from src.app import app
    from src.dependencies import get_settings

    get_settings.cache_clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _shared(public: bool):
    return (patch("src.routes.pages.repo.shared_page", return_value=_row(public)),
            patch("src.routes.pages_view.load_page", return_value=(PAGE, False)),
            patch("src.routes.pages.pt.readable", return_value=[{"key": "de", "label": "Deutsch"}]))


def test_an_open_link_needs_no_account_and_keeps_search_engines_out(client_ohne_sitzung):
    a, b, c = _shared(public=True)
    with a, b, c:
        r = client_ohne_sitzung.get(f"/pages/shared/{CODE}")
    assert r.status_code == 200, "401 heisst, das Praefix fehlt im Torwaechter"
    assert r.json()["page"]["sections"][0]["title"] == "Regression"
    assert "noindex" in r.headers["x-robots-tag"]


def test_a_link_for_kis_accounts_asks_for_the_login(client_ohne_sitzung):
    a, b, c = _shared(public=False)
    with a, b, c:
        r = client_ohne_sitzung.get(f"/pages/shared/{CODE}")
    assert r.status_code == 401


def test_a_collection_without_account_lists_only_open_pages(client_ohne_sitzung):
    with patch("src.routes.pages.repo.collection", return_value={"user_id": 7, "enabled": True, "owner_name": "f f", "pages": []}) as abfrage:
        r = client_ohne_sitzung.get("/pages/collection/wqH6UD7FJR3PSCgm")
    assert abfrage.call_args.kwargs["only_public"] is True
    # Nothing open to show, the login may reveal the rest.
    assert r.status_code == 401


def _collection(enabled: bool):
    return patch("src.routes.pages.repo.collection",
                 return_value={"user_id": 7, "enabled": enabled, "owner_name": "f f", "pages": []})


@pytest.fixture
def angemeldet():
    """A askFrancis account, the person whose id the test sets."""
    from src.app import app
    from src.dependencies import get_current_user
    from src.dependencies_rbac import get_user_permissions
    from src.permissions import resolve_user_permissions
    from src.security.auth import verify_auth

    wer = {"user_id": 3}
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": wer["user_id"], "email": "a@b.de", "role": "staff"}
    app.dependency_overrides[get_user_permissions] = lambda: resolve_user_permissions("admin", None, True)
    yield TestClient(app), wer
    app.dependency_overrides.clear()


def test_an_overview_not_shared_asks_for_the_login_without_account(client_ohne_sitzung):
    with _collection(enabled=False):
        r = client_ohne_sitzung.get("/pages/collection/wqH6UD7FJR3PSCgm")
    assert r.status_code == 401


def test_an_overview_not_shared_is_gone_for_others_and_open_for_its_owner(angemeldet):
    client, wer = angemeldet
    with _collection(enabled=False):
        assert client.get("/pages/collection/wqH6UD7FJR3PSCgm").status_code == 404
        wer["user_id"] = 7
        r = client.get("/pages/collection/wqH6UD7FJR3PSCgm")
    assert r.status_code == 200 and r.json()["own"] is True and r.json()["shared"] is False


def test_a_shared_overview_opens_for_other_accounts(angemeldet):
    client, _ = angemeldet
    with _collection(enabled=True):
        r = client.get("/pages/collection/wqH6UD7FJR3PSCgm")
    assert r.status_code == 200 and r.json()["own"] is False


def test_the_overview_switch_is_not_taken_for_a_page(angemeldet):
    client, _ = angemeldet
    with patch("src.routes.pages.repo.set_collection_share", return_value=True) as schalter:
        r = client.put("/pages/collection-share", json={"on": True})
    assert r.status_code == 200 and r.json() == {"shared": True}
    assert schalter.call_args.args == (3, True)


def test_an_expired_test_access_counts_as_no_account():
    from src.routes.pages import _logged_in

    assert _logged_in({"user_id": 3})
    assert not _logged_in({"user_id": 0})
    assert not _logged_in({"user_id": 3, "access_expires_at": (datetime.now() - timedelta(hours=1)).isoformat()})
    assert _logged_in({"user_id": 3, "access_expires_at": (datetime.now() + timedelta(hours=1)).isoformat()})
