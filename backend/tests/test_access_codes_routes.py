"""The way in without an invitation: redeem a code, renew an expired access."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.i18n import t

MORGEN = datetime.now() + timedelta(days=30)
GESTERN = datetime.now() - timedelta(days=1)


def _code(**abweichungen):
    eintrag = {
        "id": 7,
        "code": "KIS-4K2P-7RXM",
        "label": "Kollegen August",
        "role": "staff",
        "custom_role_id": None,
        "max_uses": 50,
        "used_count": 3,
        "valid_until": MORGEN,
        "access_hours": 336,
        "show_credentials": True,
        "active": True,
    }
    eintrag.update(abweichungen)
    return eintrag


def _umgebung(monkeypatch):
    monkeypatch.setenv("LDAP_BASE_DN", "dc=th-luebeck,dc=de")
    monkeypatch.setenv("LDAP_BIND_DN", "cn=admin,dc=th-luebeck,dc=de")
    monkeypatch.setenv("LDAP_BIND_PASSWORD", "admin")
    monkeypatch.setenv("LDAP_SERVER", "ldap://openldap")


@pytest.fixture
def client(monkeypatch):
    _umgebung(monkeypatch)

    from src.dependencies import get_settings
    from src.security.auth import verify_auth
    from src.app import app

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client_ohne_sitzung(monkeypatch):
    """The gate stays armed, this is what proves the open prefix."""
    _umgebung(monkeypatch)

    from src.dependencies import get_settings
    from src.app import app

    get_settings.cache_clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _sitzung():
    """The session store, same grip as in test_invites_routes.py."""
    return patch("src.routes.access_codes.get_session_store")


GUELTIG = {"code": "kis-4k2p-7rxm"}


def test_redeeming_creates_the_account_and_sets_the_deadline(client):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code()) as suchen, \
         patch("src.routes.access_codes.new_username", return_value="ab234567"), \
         patch("src.routes.access_codes.generate_password", return_value="s3cr3t-pw"), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "ab234567", "display_name": "ab234567",
             "email": None, "role": "staff", "custom_role_id": None,
         }) as anlegen, \
         patch("src.routes.access_codes.repo.set_user_access") as frist, \
         patch("src.routes.access_codes.demo_module_zuweisen"), \
         _sitzung() as sitzung:
        sitzung.return_value.create.return_value = "sitzungsschluessel"
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 200
    assert r.json()["username"] == "ab234567"
    assert r.json()["password"] == "s3cr3t-pw"
    # Sloppy typing gets repaired before the lookup.
    suchen.assert_called_once_with("KIS-4K2P-7RXM")
    assert anlegen.call_args.kwargs["email"] is None
    assert anlegen.call_args.kwargs["given_name"] == ""
    assert anlegen.call_args.kwargs["surname"] == ""
    assert anlegen.call_args.kwargs["password"] == "s3cr3t-pw"
    assert frist.call_args.kwargs["code_id"] == 7
    assert r.cookies.get("session") == "sitzungsschluessel"
    assert sitzung.return_value.create.call_args.kwargs["data"]["access_expires_at"]


def test_redeeming_returns_a_generated_password_that_is_not_empty(client):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code()), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "ab234567", "display_name": "ab234567",
             "email": None, "role": "staff", "custom_role_id": None,
         }), \
         patch("src.routes.access_codes.repo.set_user_access"), \
         patch("src.routes.access_codes.demo_module_zuweisen"), \
         _sitzung():
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 200
    assert r.json()["password"] != ""


def test_redeeming_with_an_unlimited_code_sets_no_deadline(client):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code(access_hours=None)), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "max.mustermann", "display_name": "Max Mustermann",
             "email": "max.mustermann@demo.kis.local", "role": "staff", "custom_role_id": None,
         }), \
         patch("src.routes.access_codes.repo.set_user_access") as frist, \
         patch("src.routes.access_codes.demo_module_zuweisen"), \
         _sitzung() as sitzung:
        sitzung.return_value.create.return_value = "sitzungsschluessel"
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 200
    assert frist.call_args.kwargs["expires_at"] is None
    assert sitzung.return_value.create.call_args.kwargs["data"]["access_expires_at"] is None





def test_redeeming_sets_a_deadline_in_hours_not_days(client):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code(access_hours=12)), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "max.mustermann", "display_name": "Max Mustermann",
             "email": "max.mustermann@demo.kis.local", "role": "staff", "custom_role_id": None,
         }), \
         patch("src.routes.access_codes.repo.set_user_access") as frist, \
         patch("src.routes.access_codes.demo_module_zuweisen"), \
         _sitzung():
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 200
    erwartet = datetime.now() + timedelta(hours=12)
    tatsaechlich = frist.call_args.kwargs["expires_at"]
    assert abs((tatsaechlich - erwartet).total_seconds()) < 5, \
        "eine Veranstaltung mit 12 Stunden darf nicht 12 Tage laufen"


def test_redeeming_reports_whether_credentials_should_be_shown(client):
    with patch("src.routes.access_codes.repo.get_code_by_code",
               return_value=_code(show_credentials=False)), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "max.mustermann", "display_name": "Max Mustermann",
             "email": "max.mustermann@demo.kis.local", "role": "staff", "custom_role_id": None,
         }), \
         patch("src.routes.access_codes.repo.set_user_access"), \
         patch("src.routes.access_codes.demo_module_zuweisen"), \
         _sitzung():
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 200
    assert r.json()["show_credentials"] is False


def test_redeeming_picks_a_free_user_name(client):
    belegt = {"ab234567": {"id": 1}}
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code()), \
         patch("src.routes.access_codes.new_username", return_value="ab234567"), \
         patch("src.routes.access_codes.database.get_user_by_username",
               side_effect=lambda u: belegt.get(u)), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "ab2345672", "display_name": "ab2345672",
             "email": "ab2345672@demo.kis.local", "role": "staff", "custom_role_id": None,
         }) as anlegen, \
         patch("src.routes.access_codes.repo.set_user_access"), \
         patch("src.routes.access_codes.demo_module_zuweisen"), \
         _sitzung():
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 200
    assert anlegen.call_args.kwargs["uid"] == "ab2345672"


def test_an_unknown_code_is_refused(client):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=None):
        r = client.post("/access-codes/redeem", json=GUELTIG)
    assert r.status_code == 404


@pytest.mark.parametrize("abweichung", [
    {"active": False},
    {"valid_until": GESTERN},
    {"used_count": 50},
])
def test_a_dead_code_creates_nothing(client, abweichung):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code(**abweichung)), \
         patch("src.routes.access_codes.provision_account") as anlegen:
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 410
    anlegen.assert_not_called()


def test_a_lost_race_for_the_last_seat_creates_nothing(client):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code()), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=False), \
         patch("src.routes.access_codes.provision_account") as anlegen:
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 410
    anlegen.assert_not_called()


def test_a_failing_creation_gives_the_seat_back(client):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code()), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", side_effect=RuntimeError("ldap")), \
         patch("src.routes.access_codes.repo.release_use") as zurueck:
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 500
    zurueck.assert_called_once_with(7)


def test_a_failing_deadline_write_deactivates_the_fresh_account(client):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code()), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "max.mustermann", "display_name": "Max Mustermann",
             "email": "max.mustermann@demo.kis.local", "role": "staff", "custom_role_id": None,
         }), \
         patch("src.routes.access_codes.repo.set_user_access", side_effect=RuntimeError("db down")), \
         patch("src.routes.access_codes.database.remove_from_whitelist"), \
         patch("src.routes.access_codes.database.update_user") as abschalten:
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 500
    assert abschalten.call_args.args[0] == 42
    assert abschalten.call_args.args[-1] == 0


def test_a_failing_deadline_write_also_drops_the_whitelist_entry(client):
    """Switching off alone is not enough, the login rebuilds active from the whitelist."""
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code()), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "max.mustermann", "display_name": "Max Mustermann",
             "email": "max.mustermann@demo.kis.local", "role": "staff", "custom_role_id": None,
         }), \
         patch("src.routes.access_codes.repo.set_user_access", side_effect=RuntimeError("db down")), \
         patch("src.routes.access_codes.database.update_user"), \
         patch("src.routes.access_codes.database.remove_from_whitelist") as streichen:
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 500
    streichen.assert_called_once_with("max.mustermann@demo.kis.local")


def test_a_code_whose_custom_role_is_gone_creates_nothing(client):
    with patch("src.routes.access_codes.repo.get_code_by_code",
               return_value=_code(role="custom", custom_role_id=9)), \
         patch("src.routes.access_codes.database.get_custom_role", return_value=None) as rolle, \
         patch("src.routes.access_codes.repo.claim_use") as platz, \
         patch("src.routes.access_codes.provision_account") as anlegen:
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 410
    assert r.json()["detail"] == t("access.codeNotValid", "de")
    rolle.assert_called_once_with(9)
    platz.assert_not_called()
    anlegen.assert_not_called()


def test_a_code_with_a_living_custom_role_still_works(client):
    with patch("src.routes.access_codes.repo.get_code_by_code",
               return_value=_code(role="custom", custom_role_id=9)), \
         patch("src.routes.access_codes.database.get_custom_role",
               return_value={"id": 9, "name": "Testrolle", "permissions": []}), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "max.mustermann", "display_name": "Max Mustermann",
             "email": "max.mustermann@demo.kis.local", "role": "custom", "custom_role_id": 9,
         }) as anlegen, \
         patch("src.routes.access_codes.repo.set_user_access"), \
         patch("src.routes.access_codes.demo_module_zuweisen"), \
         _sitzung():
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 200
    assert anlegen.call_args.kwargs["custom_role_id"] == 9


VERLAENGERN = {"username": "max.mustermann", "password": "geheim123", "code": "KIS-4K2P-7RXM"}


def test_renewing_moves_the_deadline_and_logs_in(client):
    konto = {"id": 42, "ldap_username": "max.mustermann", "display_name": "Max Mustermann",
             "email": "max.mustermann@demo.kis.local", "role": "staff", "custom_role_id": None,
             "access_expires_at": GESTERN}
    with patch("src.routes.access_codes.authenticate", return_value=konto), \
         patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code()), \
         patch("src.routes.access_codes.repo.set_user_access") as frist, \
         _sitzung() as sitzung:
        sitzung.return_value.create.return_value = "sitzungsschluessel"
        r = client.post("/access-codes/renew", json=VERLAENGERN)

    assert r.status_code == 200
    assert frist.call_args[0][0] == 42
    assert r.cookies.get("session") == "sitzungsschluessel"


def test_renewing_with_an_unlimited_code_sets_no_deadline(client):
    konto = {"id": 42, "ldap_username": "max.mustermann", "display_name": "Max Mustermann",
             "email": "max.mustermann@demo.kis.local", "role": "staff", "custom_role_id": None,
             "access_expires_at": GESTERN}
    with patch("src.routes.access_codes.authenticate", return_value=konto), \
         patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code(access_hours=None)), \
         patch("src.routes.access_codes.repo.set_user_access") as frist, \
         _sitzung() as sitzung:
        sitzung.return_value.create.return_value = "sitzungsschluessel"
        r = client.post("/access-codes/renew", json=VERLAENGERN)

    assert r.status_code == 200
    assert frist.call_args.kwargs["expires_at"] is None
    assert sitzung.return_value.create.call_args.kwargs["data"]["access_expires_at"] is None


def test_renewing_works_even_when_every_seat_is_taken(client):
    konto = {"id": 42, "ldap_username": "max.mustermann", "display_name": "Max Mustermann",
             "email": "max.mustermann@demo.kis.local", "role": "staff", "custom_role_id": None,
             "access_expires_at": GESTERN}
    with patch("src.routes.access_codes.authenticate", return_value=konto), \
         patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code(used_count=50)), \
         patch("src.routes.access_codes.repo.set_user_access"), _sitzung():
        r = client.post("/access-codes/renew", json=VERLAENGERN)

    assert r.status_code == 200, "Verlaengern belegt keinen Platz"


def test_renewing_a_switched_off_code_is_refused(client):
    konto = {"id": 42, "ldap_username": "max.mustermann", "display_name": "M", "email": None,
             "role": "staff", "custom_role_id": None, "active": 1, "access_expires_at": GESTERN}
    with patch("src.routes.access_codes.authenticate", return_value=konto), \
         patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code(active=False)), \
         patch("src.routes.access_codes.repo.set_user_access") as frist:
        r = client.post("/access-codes/renew", json=VERLAENGERN)

    assert r.status_code == 410
    frist.assert_not_called()


def test_a_normal_account_cannot_give_itself_a_deadline(client):
    konto = {"id": 5, "ldap_username": "hamid", "display_name": "H", "email": None,
             "role": "admin", "custom_role_id": None, "active": 1, "access_expires_at": None}
    with patch("src.routes.access_codes.authenticate", return_value=konto), \
         patch("src.routes.access_codes.repo.set_user_access") as frist:
        r = client.post("/access-codes/renew", json=VERLAENGERN)

    assert r.status_code == 403
    frist.assert_not_called()


def test_a_deactivated_account_cannot_renew_itself_back_in(client):
    konto = {"id": 42, "ldap_username": "max.mustermann", "display_name": "M", "email": None,
             "role": "staff", "custom_role_id": None, "active": 0, "access_expires_at": GESTERN}
    with patch("src.routes.access_codes.authenticate", return_value=konto), \
         patch("src.routes.access_codes.repo.set_user_access") as frist:
        r = client.post("/access-codes/renew", json=VERLAENGERN)

    assert r.status_code == 403
    assert r.json()["detail"] == "account_not_activated"
    frist.assert_not_called()


def test_renewing_with_a_wrong_password_is_refused(client):
    with patch("src.routes.access_codes.authenticate", return_value=None), \
         patch("src.routes.access_codes.repo.set_user_access") as frist:
        r = client.post("/access-codes/renew", json=VERLAENGERN)

    assert r.status_code == 401
    frist.assert_not_called()


# Without the entry in _OPEN_PREFIXES every route below answers 401.
def test_redeeming_needs_no_session(client_ohne_sitzung):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=None):
        r = client_ohne_sitzung.post("/access-codes/redeem", json=GUELTIG)
    assert r.status_code == 404, "401 heisst, das Praefix fehlt im Torwaechter"


def test_renewing_needs_no_session(client_ohne_sitzung):
    with patch("src.routes.access_codes.authenticate", return_value=None):
        r = client_ohne_sitzung.post("/access-codes/renew", json=VERLAENGERN)
    assert r.status_code == 401
    # The gate answers auth.notAuthenticated, the route answers this - proves the gate let it through.
    assert r.json()["detail"] == t("access.invalidCredentials", "de")


def test_redeeming_hands_the_demo_module_to_the_shared_place(client):
    """Same assignment as every other way in, the service decides the rest."""
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code()), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "ab234567", "display_name": "ab234567",
             "email": None, "role": "staff", "custom_role_id": None,
         }), \
         patch("src.routes.access_codes.repo.set_user_access"), \
         patch("src.routes.access_codes.demo_module_zuweisen") as zuweisen, \
         _sitzung():
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 200
    zuweisen.assert_called_once_with(42)


def test_redeeming_enrolls_the_new_account_into_the_codes_workspaces(client):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code()), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "ab234567", "display_name": "ab234567",
             "email": None, "role": "staff", "custom_role_id": None,
         }), \
         patch("src.routes.access_codes.repo.set_user_access"), \
         patch("src.routes.access_codes.demo_module_zuweisen"), \
         patch("src.routes.access_codes.repo.enroll_into_code_workspaces") as einschreiben, \
         _sitzung():
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 200
    einschreiben.assert_called_once_with(7, [42])


def test_a_failed_enrollment_never_blocks_redeeming(client):
    with patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code()), \
         patch("src.routes.access_codes.database.get_user_by_username", return_value=None), \
         patch("src.routes.access_codes.repo.claim_use", return_value=True), \
         patch("src.routes.access_codes.provision_account", return_value={
             "user_id": 42, "username": "ab234567", "display_name": "ab234567",
             "email": None, "role": "staff", "custom_role_id": None,
         }), \
         patch("src.routes.access_codes.repo.set_user_access"), \
         patch("src.routes.access_codes.demo_module_zuweisen"), \
         patch("src.routes.access_codes.repo.enroll_into_code_workspaces",
               side_effect=RuntimeError("db weg")), \
         _sitzung():
        r = client.post("/access-codes/redeem", json=GUELTIG)

    assert r.status_code == 200


def test_renewing_enrolls_into_the_workspaces_of_the_code_used(client):
    konto = {"id": 42, "ldap_username": "max.mustermann", "display_name": "Max Mustermann",
             "email": "max.mustermann@demo.kis.local", "role": "staff", "custom_role_id": None,
             "access_expires_at": GESTERN}
    with patch("src.routes.access_codes.authenticate", return_value=konto), \
         patch("src.routes.access_codes.repo.get_code_by_code", return_value=_code(id=9)), \
         patch("src.routes.access_codes.repo.set_user_access"), \
         patch("src.routes.access_codes.repo.enroll_into_code_workspaces") as einschreiben, \
         _sitzung():
        r = client.post("/access-codes/renew", json=VERLAENGERN)

    assert r.status_code == 200
    einschreiben.assert_called_once_with(9, [42])
