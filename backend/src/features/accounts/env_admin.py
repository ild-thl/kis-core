"""The admin account from the .env, kept in step with it on every start."""
from loguru import logger

from src import database
from src.features.accounts.passwords import PasswordTooLongError, hash_password
from src.features.accounts.uid import ist_anmeldename, slugify_uid

# Which row the .env belongs to, so a renamed admin is still found next start.
_MERKZETTEL = "env_admin_user_id"
_FALLBACK_UID = "admin"


def ensure_env_admin(email: str, password: str, username: str = "") -> int | None:
    """Writes user name, mail and password from the .env onto the admin account."""
    adresse = (email or "").strip().lower()
    if not adresse or not password:
        return None

    name = _gewuenschter_name(username, adresse)
    konto = _finde_konto(adresse, name)

    if konto is None:
        return _neu_anlegen(name, adresse, password)

    _abgleichen(konto, name, adresse, password)
    return konto["id"]


def _gewuenschter_name(username: str, adresse: str) -> str:
    """The name from the .env, or the local part of the mail when none is given."""
    gewuenscht = (username or "").strip().lower()
    if gewuenscht:
        return gewuenscht
    return slugify_uid(adresse.split("@", 1)[0]) or _FALLBACK_UID


def _finde_konto(adresse: str, name: str):
    """The noted row first, then the mail, then the name."""
    gemerkt = database.get_setting(_MERKZETTEL, "")
    if gemerkt.isdigit():
        konto = database.get_user_by_id(int(gemerkt))
        if konto is not None:
            return konto
        logger.warning("Noted admin row {} is gone, looking it up again", gemerkt)
    return database.get_user_by_email(adresse) or database.get_user_by_username(name)


def _neu_anlegen(name: str, adresse: str, password: str) -> int | None:
    """Creates the admin and notes which row it is."""
    database.add_to_whitelist(adresse)
    user_id = database.create_user(
        username=name,
        display_name="Admin",
        email=adresse,
        active=1,
        role="admin",
        password_hash=_hash_oder_none(password),
    )
    database.set_setting(_MERKZETTEL, str(user_id))
    logger.info("Admin from the .env created (uid={})", name)
    return user_id


def _abgleichen(konto, name: str, adresse: str, password: str) -> None:
    """Puts the three values from the .env onto the existing row."""
    user_id = konto["id"]
    database.set_setting(_MERKZETTEL, str(user_id))
    database.add_to_whitelist(adresse)

    _rename_and_remail(user_id, _pruefe_name(konto, name), adresse)

    neuer_hash = _hash_oder_none(password)
    if neuer_hash is not None:
        database.set_user_password(user_id, neuer_hash)
    logger.info("Admin from the .env brought in line (uid={})", name)


def _pruefe_name(konto, name: str) -> str:
    """Keeps the old name when the wished one would break the login or is taken."""
    alt = konto["username"]
    if name == alt:
        return alt
    if not ist_anmeldename(name):
        logger.error("ADMIN_USERNAME '{}' is no usable user name, keeping '{}'", name, alt)
        return alt
    belegt = database.get_user_by_username(name)
    if belegt is not None and belegt["id"] != konto["id"]:
        logger.error("ADMIN_USERNAME '{}' belongs to somebody else, keeping '{}'", name, alt)
        return alt
    return name


def _rename_and_remail(user_id: int, name: str, adresse: str) -> None:
    """Writes name and mail in one statement, both are unique per row."""
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET username = %s, email = %s WHERE id = %s",
                (name, adresse, user_id),
            )
        conn.commit()


def _hash_oder_none(password: str) -> str | None:
    """A password beyond the limit must not stop the start, it only stays unusable."""
    try:
        return hash_password(password)
    except PasswordTooLongError:
        logger.error("ADMIN_PASSWORD is too long, the admin keeps the password it had")
        return None
