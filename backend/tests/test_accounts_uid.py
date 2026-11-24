from src.features.accounts.uid import ist_anmeldename, slugify_uid, unique_uid


def test_slugify_keeps_a_plain_local_part():
    assert slugify_uid("max.mustermann") == "max.mustermann"


def test_slugify_lowers_case_and_replaces_umlauts():
    assert slugify_uid("Jörg.Müller") == "joerg.mueller"


def test_slugify_drops_characters_a_login_name_does_not_accept():
    assert slugify_uid("anna+test") == "annatest"


def test_slugify_returns_none_when_nothing_usable_is_left():
    assert slugify_uid("!!!") is None
    assert slugify_uid("a") is None


def test_unique_uid_returns_the_base_when_it_is_free():
    assert unique_uid("max.mustermann", lambda _: False) == "max.mustermann"


def test_unique_uid_appends_the_smallest_free_number():
    belegt = {"max.mustermann", "max.mustermann2"}
    assert unique_uid("max.mustermann", lambda u: u in belegt) == "max.mustermann3"


def test_unique_uid_shortens_the_base_so_the_number_still_fits():
    lang = "a" * 32
    ergebnis = unique_uid(lang, lambda u: u == lang)
    assert len(ergebnis) <= 32
    assert ergebnis.endswith("2")


def test_a_normal_user_name_is_a_login_name():
    assert ist_anmeldename("max.mustermann") is True


def test_an_at_sign_is_never_a_login_name():
    # The login field tells a mail from a name by the @, so a name must not carry one.
    assert ist_anmeldename("max@th-luebeck.de") is False


def test_the_slug_never_produces_something_with_an_at_sign():
    assert "@" not in (slugify_uid("max@th-luebeck.de") or "")


def test_a_slug_is_always_a_login_name():
    for eingabe in ("Max Mustermann", "Hans Müller", "a.b-c_d", "max@th-luebeck.de"):
        erg = slugify_uid(eingabe)
        if erg is not None:
            assert ist_anmeldename(erg) is True


def test_empty_and_too_short_are_no_login_names():
    assert ist_anmeldename("") is False
    assert ist_anmeldename("a") is False


def test_upper_case_is_no_login_name():
    assert ist_anmeldename("Max") is False
