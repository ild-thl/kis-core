"""The evaluation in the database: config in settings, answers in their own table."""
import json
from datetime import datetime

import psycopg2.extras

from src.core.db.pool import get_connection
from src.features.admin.repository.settings import get_setting, set_setting
from src.features.evaluation.service import default_config


def get_config() -> dict:
    """Reads the evaluation out of settings, the default seed content where nothing was saved yet.

    The on/off switch is read on its own: it can be flipped before the form
    was ever saved, so it must not fall back to the seed's "active": False
    together with the rest of the content.

    The seed applies to the whole form, never field by field, so a text the
    admin deliberately cleared stays cleared instead of reappearing.
    """
    voreinstellung = default_config()
    fragen_roh = get_setting("evaluation_questions")
    gespeichert = bool(fragen_roh)
    return {
        "active": get_setting("evaluation_active") == "true",
        "for_all": get_setting("evaluation_for_all") == "true",
        "reveal_round": _reveal_round(),
        "title": get_setting("evaluation_title") if gespeichert else voreinstellung["title"],
        "intro_text": get_setting("evaluation_intro_text") if gespeichert else voreinstellung["intro_text"],
        "intro_link_label": get_setting("evaluation_intro_link_label"),
        "intro_link_url": get_setting("evaluation_intro_link_url"),
        "outro_text": get_setting("evaluation_outro_text") if gespeichert else voreinstellung["outro_text"],
        "outro_link_label": get_setting("evaluation_outro_link_label"),
        "outro_link_url": get_setting("evaluation_outro_link_url"),
        "contact_email": get_setting("evaluation_contact_email") if gespeichert else (voreinstellung["contact_email"] or get_setting("legal_contact_email")),
        "questions": json.loads(fragen_roh) if gespeichert else voreinstellung["questions"],
    }


def save_config(config: dict) -> None:
    """Overwrites the whole evaluation, an edit always replaces what was there."""
    set_setting("evaluation_title", config["title"])
    set_setting("evaluation_intro_text", config["intro_text"])
    set_setting("evaluation_intro_link_label", config["intro_link_label"])
    set_setting("evaluation_intro_link_url", config["intro_link_url"])
    set_setting("evaluation_outro_text", config["outro_text"])
    set_setting("evaluation_outro_link_label", config["outro_link_label"])
    set_setting("evaluation_outro_link_url", config["outro_link_url"])
    set_setting("evaluation_contact_email", config["contact_email"])
    set_setting("evaluation_questions", json.dumps(config["questions"]))


def _reveal_round() -> int:
    """The round a dismissed invite is compared against, unset counts as zero."""
    roh = get_setting("evaluation_reveal_round", "0")
    return int(roh) if roh.isdigit() else 0


def _start_new_round() -> None:
    """A fresh round brings the invite back for everyone who clicked it away."""
    set_setting("evaluation_reveal_round", str(_reveal_round() + 1))


def set_active(active: bool) -> None:
    """The quick on/off switch, everything else about the evaluation stays untouched."""
    if active and get_setting("evaluation_active") != "true":
        _start_new_round()
    set_setting("evaluation_active", "true" if active else "false")


def set_for_all(for_all: bool) -> None:
    """Opens the evaluation to every account, no code and no permission needed."""
    if for_all and get_setting("evaluation_for_all") != "true":
        _start_new_round()
    set_setting("evaluation_for_all", "true" if for_all else "false")


def has_platform_activity(user_id: int) -> bool:
    """Whether this account has ever done more than log in, so the invite reaches people who actually tried something."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT
                       EXISTS(SELECT 1 FROM users WHERE id = %(uid)s AND tour_seen_at IS NOT NULL)
                    OR EXISTS(SELECT 1 FROM jobs WHERE user_id = %(uid)s)
                    OR EXISTS(
                           SELECT 1 FROM aia_workspaces w
                           JOIN aia_sources s ON s.workspace_id = w.id
                           WHERE w.user_id = %(uid)s
                       )
                    OR EXISTS(SELECT 1 FROM aia_messages WHERE user_id = %(uid)s AND role = 'user')""",
                {"uid": user_id},
            )
            return cur.fetchone()[0]


def has_responded(user_id: int) -> bool:
    """Whether this account already sent in an answer, used to hide the invite afterwards."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM evaluation_responses WHERE user_id = %s LIMIT 1", (user_id,))
            return cur.fetchone() is not None


def list_responses(since: datetime | None) -> list[dict]:
    """Submissions for the statistics, without the account behind them."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if since is None:
                cur.execute("SELECT answers, created_at FROM evaluation_responses ORDER BY created_at")
            else:
                cur.execute(
                    "SELECT answers, created_at FROM evaluation_responses "
                    "WHERE created_at >= %s ORDER BY created_at",
                    (since,),
                )
            return [dict(zeile) for zeile in cur.fetchall()]


def create_response(user_id: int, answers: list[dict]) -> int:
    """Stores one submission, returns its id."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO evaluation_responses (user_id, answers) VALUES (%s, %s) RETURNING id",
                (user_id, psycopg2.extras.Json(answers)),
            )
            response_id = cur.fetchone()[0]
        conn.commit()
        return response_id
