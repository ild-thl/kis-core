"""The link guard: only plain public http(s) links reach the fetcher."""
import ipaddress
import socket

import httpx
import pytest

from src.services import web_page_fetch as wpf


@pytest.fixture
def dns(monkeypatch):
    """Name table instead of real DNS, literal addresses pass through."""
    tabelle = {
        "example.org": ["93.184.216.34"],
        "intern.example": ["10.0.0.5"],
        "beides.example": ["93.184.216.34", "10.0.0.5"],
        "askf-redis": ["172.18.0.3"],
    }

    def _aufloesen(host):
        if host in tabelle:
            return tabelle[host]
        try:
            ipaddress.ip_address(host)
            return [host]
        except ValueError:
            raise socket.gaierror("kein Name")

    monkeypatch.setattr(wpf, "_resolve", _aufloesen)


def _abgelehnt(link, key, status):
    with pytest.raises(wpf.LinkError) as exc:
        wpf.validate_url(link)
    assert exc.value.key == key
    assert exc.value.status == status


@pytest.mark.parametrize("link", [
    "ftp://example.org/datei",
    "javascript:alert(1)",
    "mailto:a@example.org",
    "example.org/seite",
    "http:///seite",
])
def test_nur_http_und_https(dns, link):
    _abgelehnt(link, "ai.link.invalid", 400)


def test_nutzername_im_link_wird_abgelehnt(dns):
    _abgelehnt("https://user:pass@example.org/", "ai.link.invalid", 400)


@pytest.mark.parametrize("link", [
    "http://example.org:8080/",
    "http://example.org:11434/",
    "https://example.org:6379/",
])
def test_nur_port_80_und_443(dns, link):
    _abgelehnt(link, "ai.link.invalid", 400)


def test_port_80_und_443_gehen(dns):
    assert wpf.validate_url("http://example.org:80/a") == "http://example.org:80/a"
    assert wpf.validate_url("https://example.org:443/a") == "https://example.org:443/a"


def test_zu_langer_link(dns):
    _abgelehnt("https://example.org/" + "a" * 2000, "ai.link.invalid", 400)


@pytest.mark.parametrize("link", [
    "https://example.org/a\nb",
    "https://example.org/a\tb",
    "https://example.org/a\rb",
])
def test_steuerzeichen_im_link_werden_abgelehnt(dns, link):
    _abgelehnt(link, "ai.link.invalid", 400)


@pytest.mark.parametrize("host", [
    "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254",
    "0.0.0.0", "224.0.0.1", "100.64.0.1",
    "[::1]", "[fd00::1]", "[fe80::1]", "[::ffff:127.0.0.1]", "[::]",
    "localhost", "intern.example", "askf-redis", "beides.example",
])
def test_interne_adressen_sind_gesperrt(dns, host):
    _abgelehnt(f"http://{host}/", "ai.link.forbiddenAddress", 400)


def test_oeffentliche_adresse_geht(dns):
    assert wpf.validate_url("  https://example.org/seite?x=1  ") == "https://example.org/seite?x=1"
    assert wpf.validate_url("http://93.184.216.34/") == "http://93.184.216.34/"


def test_name_loest_nicht_auf(dns):
    _abgelehnt("https://gibt.es.nicht.example/", "ai.link.unreachable", 502)


def test_normalisieren_fuer_die_dublette():
    assert wpf.normalize_url("HTTPS://Example.ORG/Seite/#oben") == "https://example.org/Seite"
    assert wpf.normalize_url("https://example.org/Seite") == wpf.normalize_url("https://example.org/Seite/")
    assert wpf.normalize_url("https://example.org/a?x=1") != wpf.normalize_url("https://example.org/a?x=2")
    assert wpf.normalize_url("https://example.org:443/a") == "https://example.org/a"


def _client(handler):
    return httpx.MockTransport(handler)


def test_weiterleitung_nach_innen_wird_gesperrt(dns):
    def handler(request):
        return httpx.Response(302, headers={"location": "http://10.0.0.5/geheim"})

    with pytest.raises(wpf.LinkError) as exc:
        wpf.fetch_page("https://example.org/start", transport=_client(handler))
    assert exc.value.key == "ai.link.forbiddenAddress"


def test_weiterleitung_auf_anderen_port_wird_gesperrt(dns):
    def handler(request):
        return httpx.Response(301, headers={"location": "http://example.org:11434/"})

    with pytest.raises(wpf.LinkError) as exc:
        wpf.fetch_page("https://example.org/start", transport=_client(handler))
    assert exc.value.key == "ai.link.invalid"


def test_weiterleitung_mit_steuerzeichen_wird_abgelehnt(dns):
    def handler(request):
        return httpx.Response(302, headers={"location": "https://example.org/x\ty"})

    with pytest.raises(wpf.LinkError) as exc:
        wpf.fetch_page("https://example.org/start", transport=_client(handler))
    assert exc.value.key == "ai.link.invalid"
    assert exc.value.status == 400


def test_sechste_weiterleitung_bricht_ab(dns):
    zaehler = {"n": 0}

    def handler(request):
        zaehler["n"] += 1
        return httpx.Response(302, headers={"location": f"https://example.org/hop{zaehler['n']}"})

    with pytest.raises(wpf.LinkError) as exc:
        wpf.fetch_page("https://example.org/start", transport=_client(handler))
    assert exc.value.key == "ai.link.tooManyRedirects"
    assert zaehler["n"] == 6


def test_relative_weiterleitung_wird_aufgeloest(dns):
    gesehen = []

    def handler(request):
        gesehen.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/ziel"})
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=b"<p>hi</p>")

    seite = wpf.fetch_page("https://example.org/start", transport=_client(handler))
    assert gesehen == ["https://example.org/start", "https://example.org/ziel"]
    assert seite.final_url == "https://example.org/ziel"
    assert seite.kind == "html"


def test_groessendeckel_greift_beim_streamen(dns, monkeypatch):
    monkeypatch.setattr(wpf, "WEB_PAGE_MAX_HTML_BYTES", 10)

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 100)

    with pytest.raises(wpf.LinkError) as exc:
        wpf.fetch_page("https://example.org/", transport=_client(handler))
    assert exc.value.key == "ai.link.tooLarge"
    assert exc.value.status == 413


def test_pdf_deckel_ist_der_groessere(dns, monkeypatch):
    monkeypatch.setattr(wpf, "WEB_PAGE_MAX_HTML_BYTES", 10)
    monkeypatch.setattr(wpf, "WEB_PAGE_MAX_PDF_BYTES", 1000)

    def handler(request):
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4" + b"x" * 100)

    seite = wpf.fetch_page("https://example.org/skript.pdf", transport=_client(handler))
    assert seite.kind == "pdf"


@pytest.mark.parametrize("content_type,body,kind", [
    ("text/html; charset=utf-8", b"<p>x</p>", "html"),
    ("application/xhtml+xml", b"<p>x</p>", "html"),
    ("text/plain", b"nur text", "text"),
    ("application/pdf", b"%PDF-1.4", "pdf"),
    ("application/octet-stream", b"%PDF-1.7 xyz", "pdf"),
])
def test_typ_weiche(dns, content_type, body, kind):
    def handler(request):
        return httpx.Response(200, headers={"content-type": content_type}, content=body)

    seite = wpf.fetch_page("https://example.org/", transport=_client(handler))
    assert seite.kind == kind
    assert seite.body == body


def test_anderer_typ_wird_abgelehnt(dns):
    def handler(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG")

    with pytest.raises(wpf.LinkError) as exc:
        wpf.fetch_page("https://example.org/bild.png", transport=_client(handler))
    assert exc.value.key == "ai.link.unsupportedType"
    assert exc.value.status == 415


@pytest.mark.parametrize("status", [401, 403])
def test_login_seiten_geben_die_login_meldung(dns, status):
    def handler(request):
        return httpx.Response(status, content=b"nein")

    with pytest.raises(wpf.LinkError) as exc:
        wpf.fetch_page("https://example.org/", transport=_client(handler))
    assert exc.value.key == "ai.link.loginRequired"
    assert exc.value.status == 502


def test_serverfehler_traegt_den_status(dns):
    def handler(request):
        return httpx.Response(503, content=b"weg")

    with pytest.raises(wpf.LinkError) as exc:
        wpf.fetch_page("https://example.org/", transport=_client(handler))
    assert exc.value.key == "ai.link.httpError"
    assert exc.value.params == {"status": 503}


def test_verbindungsfehler_heisst_antwortet_nicht(dns):
    def handler(request):
        raise httpx.ConnectTimeout("zu langsam")

    with pytest.raises(wpf.LinkError) as exc:
        wpf.fetch_page("https://example.org/", transport=_client(handler))
    assert exc.value.key == "ai.link.unreachable"


def test_abruf_schickt_eigenen_user_agent_und_folgt_nicht_selbst(dns):
    gesehen = {}

    def handler(request):
        gesehen["ua"] = request.headers.get("user-agent")
        gesehen["cookie"] = request.headers.get("cookie")
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    wpf.fetch_page("https://example.org/", transport=_client(handler))
    assert gesehen["ua"] == "askFrancis/1.0"
    assert gesehen["cookie"] is None


def test_gesamtzeit_ist_gedeckelt(dns, monkeypatch):
    monkeypatch.setattr(wpf, "WEB_PAGE_TIMEOUT_SECONDS", 0)

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>hi</p>")

    with pytest.raises(wpf.LinkError) as exc:
        wpf.fetch_page("https://example.org/", transport=_client(handler))
    assert exc.value.key == "ai.link.unreachable"
