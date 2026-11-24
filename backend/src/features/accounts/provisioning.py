"""One account, created the same way for the invitation and the access code."""
from src import database
from src.features.accounts.passwords import hash_password


def provision_account(
    *,
    uid: str,
    given_name: str,
    surname: str,
    email: str | None,
    role: str,
    custom_role_id: int | None,
    password: str,
) -> dict:
    """Creates the row in users plus the list entry, returns the session data."""
    vorname, nachname = (given_name or "").strip(), (surname or "").strip()
    display_name = " ".join(teil for teil in (vorname, nachname) if teil) or uid
    adresse = (email or "").strip() or None

    if adresse:
        database.add_to_whitelist(adresse)
    user_id = database.create_user(
        username=uid,
        display_name=display_name,
        email=adresse,
        active=1,
        role=role,
        password_hash=hash_password(password),
    )
    if role == "custom":
        database.set_user_role(user_id, "custom", custom_role_id)

    return {
        "user_id": user_id,
        "username": uid,
        "display_name": display_name,
        "email": adresse,
        "role": role,
        "custom_role_id": custom_role_id,
    }
