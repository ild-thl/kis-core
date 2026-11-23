"""Text fragments for the access codes."""

MESSAGES: dict[str, dict[str, str]] = {
    "access.codeUnknown": {
        "de": "Diesen Zugangscode gibt es nicht",
        "en": "This access code does not exist",
    },
    "access.codeNotValid": {
        "de": "Dieser Code gilt nicht mehr",
        "en": "This code is no longer valid",
    },
    "access.createFailed": {
        "de": "Das Konto konnte nicht angelegt werden",
        "en": "The account could not be created",
    },
    "access.invalidCredentials": {
        "de": "Benutzername oder Passwort stimmt nicht",
        "en": "Wrong user name or password",
    },
    "access.notATestAccount": {
        "de": "Dieses Konto laeuft nicht ab und braucht keinen Code",
        "en": "This account does not expire and needs no code",
    },
    "access.invalidCustomRole": {
        "de": "Rolle nicht gefunden",
        "en": "Role not found",
    },
    "access.notFound": {
        "de": "Diesen Zugangscode gibt es nicht",
        "en": "This access code does not exist",
    },
    "access.notFromCode": {
        "de": "Dieses Konto stammt nicht aus einem Zugangscode",
        "en": "This account does not come from an access code",
    },
    "access.passwordResetFailed": {
        "de": "Das Passwort konnte nicht geaendert werden",
        "en": "The password could not be changed",
    },
    "access.deleteAccountFailed": {
        "de": "Das Konto konnte nicht geloescht werden",
        "en": "The account could not be deleted",
    },
    "access.maxUsesBelowUsed": {
        "de": "Die Obergrenze darf nicht unter die bereits erfolgte Anzahl fallen",
        "en": "The limit cannot be set below the number already used",
    },
}
