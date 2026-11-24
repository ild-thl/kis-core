"""i18n message fragments for admin routes."""

MESSAGES: dict[str, dict[str, str]] = {
    # Tool visibility
    "admin.tools.unknownKey": {
        "de": "Unbekannter Dienst",
        "en": "Unknown service",
    },
    # Settings
    "admin.settings.unknownPingService": {
        "de": "Unbekannter Service: {service}",
        "en": "Unknown service: {service}",
    },
    "admin.settings.lastProviderRequired": {
        "de": "Mindestens ein {group}-Anbieter muss aktiv bleiben. Aktiviere zuerst einen anderen.",
        "en": "At least one {group} provider must remain active. Enable another one first.",
    },
    "admin.settings.homeNoticeTooLong": {
        "de": "Hinweistext ist zu lang (max {max} Zeichen)",
        "en": "Notice text is too long (max {max} characters)",
    },
    "admin.settings.contactEmailInvalid": {
        "de": "Die E-Mail-Adresse ist ungültig.",
        "en": "The email address is not valid.",
    },
    "admin.settings.legalTextTooLong": {
        "de": "Text ist zu lang (max {max} Zeichen)",
        "en": "Text is too long (max {max} characters)",
    },
    "admin.settings.welcomeModalTooLong": {
        "de": "Text ist zu lang (max {max} Zeichen)",
        "en": "Text is too long (max {max} characters)",
    },
    "admin.settings.diagnosisPromptTooLong": {
        "de": "Diagnose-Prompt ist zu lang (max {max} Zeichen)",
        "en": "Diagnosis prompt is too long (max {max} characters)",
    },
    "admin.settings.diagnosisPlanInvalid": {
        "de": "Fragen-Plan ist ungültig. Der Plan braucht mindestens eine Frage, und jede Frage braucht einen Fragetyp.",
        "en": "Question plan is invalid. The plan needs at least one question, and every question needs a task type.",
    },
    "admin.settings.diagnosisPlanGenerationFailed": {
        "de": "Die KI konnte keinen brauchbaren Fragensatz schreiben. Bitte noch einmal versuchen.",
        "en": "The AI could not write a usable set of questions. Please try again.",
    },
    "admin.settings.diagnosisPlanIncomplete": {
        "de": "Frage {number} ist noch nicht fertig. Jede Frage braucht einen Fragetext. Eine Auswahl-Frage braucht außerdem Antwortoptionen, davon mindestens eine als richtig markiert.",
        "en": "Question {number} is not finished. Every question needs a question text. A choice question also needs answer options, with at least one marked correct.",
    },
    "admin.settings.diagnosisPlanTooFewFreeText": {
        "de": "Der Plan braucht mindestens {min} Freitext-Fragen ohne Lösung. Nur die beurteilt die KI selbst, und nur so entsteht die Stufe aus einer echten Textprobe. Freitext-Fragen mit Lösung zählen hier nicht, die prüft der Code.",
        "en": "The plan needs at least {min} free-text questions without a solution. Only those does the AI judge itself, and only they give the level a real writing sample. Free-text questions with a solution do not count here, the code checks those.",
    },
    "admin.settings.answerMaxCharsOutOfRange": {
        "de": "Antwortlänge muss zwischen {min} und {max} Zeichen liegen",
        "en": "Answer length must be between {min} and {max} characters",
    },
    "admin.settings.diagnosisExamplesInvalid": {
        "de": "Beispiele sind ungültig. Erlaubt sind nur die Stufen A1, A2, B1, B2, C1, C2 mit Text.",
        "en": "Examples are invalid. Only the levels A1, A2, B1, B2, C1, C2 with text are allowed.",
    },
    "admin.settings.unknownModelKeys": {
        "de": "Unbekannte Model-Keys: {unknown}",
        "en": "Unknown model keys: {unknown}",
    },
    "admin.settings.modelNameEmpty": {
        "de": "Modellname für {key} darf nicht leer sein",
        "en": "Model name for {key} must not be empty",
    },
    # DeepL multi-key admin
    "admin.settings.deepl.invalidKeyId": {
        "de": "Ungültige DeepL-Key-ID.",
        "en": "Invalid DeepL key id.",
    },
    "admin.settings.deepl.keyNotFound": {
        "de": "DeepL-Key nicht gefunden.",
        "en": "DeepL key not found.",
    },
    "admin.settings.deepl.nameRequired": {
        "de": "Name darf nicht leer sein.",
        "en": "Name must not be empty.",
    },
    "admin.settings.deepl.nameTooLong": {
        "de": "Name darf höchstens 60 Zeichen lang sein.",
        "en": "Name must not exceed 60 characters.",
    },
    "admin.settings.deepl.nameTaken": {
        "de": "Ein DeepL-Key mit diesem Namen existiert bereits.",
        "en": "A DeepL key with this name already exists.",
    },
    "admin.settings.deepl.keyRequired": {
        "de": "API-Key darf nicht leer sein.",
        "en": "API key must not be empty.",
    },
    "admin.settings.deepl.keyTooLong": {
        "de": "API-Key ist zu lang (max. 200 Zeichen).",
        "en": "API key is too long (max. 200 characters).",
    },
    # Quota
    "admin.quota.unknownType": {
        "de": "Unbekannter Quota-Typ: {quota_type}",
        "en": "Unknown quota type: {quota_type}",
    },
    # Maintenance
    "admin.maintenance.reindexAlreadyRunning": {
        "de": "Reindex läuft bereits",
        "en": "Reindex already running",
    },
    # Vorraete
    "admin.pools.nothingChosen": {
        "de": "Kein Vorrat gewählt",
        "en": "No stock selected",
    },
    # Users
    "admin.user.notFound": {
        "de": "User nicht gefunden",
        "en": "User not found",
    },
    "admin.user.noEmail": {
        "de": "User hat keine Email-Adresse",
        "en": "User has no email address",
    },
    "admin.user.cannotDeleteSelf": {
        "de": "Du kannst dein eigenes Konto nicht löschen.",
        "en": "You cannot delete your own account.",
    },
    "admin.user.envAdminProtected": {
        "de": "Das Admin-Konto aus der Konfiguration kann nicht gelöscht werden.",
        "en": "The admin account from the configuration cannot be deleted.",
    },
    # Whitelist
    "admin.whitelist.invalidEmail": {
        "de": "Ungültige Email-Adresse",
        "en": "Invalid email address",
    },
    "admin.whitelist.adminProtected": {
        "de": "Die Admin-Email kann nicht aus der Whitelist entfernt werden.",
        "en": "The admin email cannot be removed from the whitelist.",
    },
    # Account creation by an admin.
    "admin.accounts.userExists": {
        "de": "Benutzer existiert bereits",
        "en": "User already exists",
    },
    "admin.accounts.invalidUid": {
        "de": "Ungültiger Benutzername (a-z, 0-9, _ . -, 2-32 Zeichen)",
        "en": "Invalid username (a-z, 0-9, _ . -, 2-32 characters)",
    },
    "admin.accounts.invalidEmail": {
        "de": "Ungültige E-Mail-Adresse",
        "en": "Invalid email address",
    },
    "admin.accounts.addFailed": {
        "de": "Konto konnte nicht angelegt werden",
        "en": "Account could not be created",
    },
    "admin.accounts.invalidCustomRole": {
        "de": "Custom Role nicht gefunden",
        "en": "Custom role not found",
    },
}
