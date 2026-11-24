from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool


from src.core.db.pool import get_connection
from src.core.db.schema_campus import create_campus_hnsw, create_campus_tables
from src.limits import IMAGE_PROVIDER_MAX_CONCURRENT, TTS_PROVIDER_MAX_CONCURRENT


# Wait time for a table lock, otherwise a restart deadlocks with running workers.
_MIGRATION_LOCK_TIMEOUT = "10s"
# Number of attempts, every statement in init_db is repeatable.
_MIGRATION_ATTEMPTS = 5

# A one-time step, not a repeatable one, see _reset_quiz_pool_once.
_QUIZ_POOL_RESET_KEY = "quiz_pool_true_false_reset_done"

# The same for grammar, see _reset_grammar_pool_once.
_GRAMMAR_POOL_RESET_KEY = "grammar_pool_task_line_reset_done"

# The trainer moved to the person, every level is assessed anew, see _reset_language_training_once.
_LANGUAGE_TRAINING_RESET_KEY = "language_training_person_reset_done"


def _reset_quiz_pool_once(cur) -> bool:
    """Drops the quiz pool once because true/false questions were added."""
    cur.execute("SELECT value FROM settings WHERE key = %s", (_QUIZ_POOL_RESET_KEY,))
    row = cur.fetchone()
    if row and row[0] == "true":
        return False
    cur.execute(
        """UPDATE aia_exercise_items i
              SET back = p.back, back_en = p.back_en, options = p.options,
                  correct_idx = p.correct_idx, explanation = p.explanation,
                  source_label = p.source_label, page_number = p.page_number,
                  start_time = p.start_time, sources = p.sources, extras = p.extras
             FROM aia_exercise_pool p
            WHERE i.pool_item_id = p.id AND p.tool = 'quiz'"""
    )
    cur.execute("DELETE FROM aia_exercise_pool WHERE tool = 'quiz'")
    cur.execute(
        """INSERT INTO settings (key, value) VALUES (%s, 'true')
           ON CONFLICT (key) DO UPDATE SET value = 'true'""",
        (_QUIZ_POOL_RESET_KEY,),
    )
    return True


def _reset_grammar_pool_once(cur) -> bool:
    """Drops the grammar pool once because the instruction line is new."""
    cur.execute("SELECT value FROM settings WHERE key = %s", (_GRAMMAR_POOL_RESET_KEY,))
    row = cur.fetchone()
    if row and row[0] == "true":
        return False
    cur.execute(
        """UPDATE aia_exercise_items i
              SET back = p.back, back_en = p.back_en, options = p.options,
                  correct_idx = p.correct_idx, explanation = p.explanation,
                  source_label = p.source_label, page_number = p.page_number,
                  start_time = p.start_time, sources = p.sources, extras = p.extras
             FROM aia_exercise_pool p
            WHERE i.pool_item_id = p.id AND p.tool = 'grammatik'"""
    )
    cur.execute("DELETE FROM aia_exercise_pool WHERE tool = 'grammatik'")
    cur.execute(
        """INSERT INTO settings (key, value) VALUES (%s, 'true')
           ON CONFLICT (key) DO UPDATE SET value = 'true'""",
        (_GRAMMAR_POOL_RESET_KEY,),
    )
    return True


def _reset_language_training_once(cur) -> bool:
    """Clears every stored level once because the trainer moved from the module to the person."""
    cur.execute("SELECT value FROM settings WHERE key = %s", (_LANGUAGE_TRAINING_RESET_KEY,))
    row = cur.fetchone()
    if row and row[0] == "true":
        return False
    cur.execute("UPDATE users SET language_level = NULL, language_level_set_at = NULL")
    cur.execute(
        """INSERT INTO settings (key, value) VALUES (%s, 'true')
           ON CONFLICT (key) DO UPDATE SET value = 'true'""",
        (_LANGUAGE_TRAINING_RESET_KEY,),
    )
    return True


def _add_provider_concurrency_once(cur) -> bool:
    """Adds providers.concurrency, seeding the measured caps only when the column is new."""
    cur.execute(
        """SELECT 1 FROM information_schema.columns
           WHERE table_schema = current_schema()
             AND table_name = 'providers'
             AND column_name = 'concurrency'"""
    )
    if cur.fetchone():
        return False
    cur.execute(
        "ALTER TABLE providers "
        "ADD COLUMN IF NOT EXISTS concurrency JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    cur.execute(
        """UPDATE providers SET concurrency = concurrency || jsonb_build_object('tts', %s::int)
           WHERE capabilities ? 'tts'""",
        (TTS_PROVIDER_MAX_CONCURRENT,),
    )
    cur.execute(
        """UPDATE providers SET concurrency = concurrency || jsonb_build_object('image', %s::int)
           WHERE capabilities ?| array['image_gen', 'image_edit']""",
        (IMAGE_PROVIDER_MAX_CONCURRENT,),
    )
    return True


def _drop_embedding_dimension_once(cur) -> bool:
    """Drops a fixed dimension of aia_chunks.embedding only while there is one, the change rebuilds the vector index."""
    cur.execute(
        """SELECT a.atttypmod FROM pg_attribute a
           JOIN pg_class c ON c.oid = a.attrelid
           WHERE c.relname = 'aia_chunks' AND c.relnamespace = current_schema()::regnamespace
             AND a.attname = 'embedding' AND NOT a.attisdropped"""
    )
    row = cur.fetchone()
    if not row or row[0] < 0:
        return False
    cur.execute("ALTER TABLE aia_chunks ALTER COLUMN embedding TYPE vector USING embedding::vector")
    return True


def _table_exists(cur, table: str) -> bool:
    """Does the table already exist?"""
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))
    return bool(cur.fetchone()[0])


def init_db(admin_email: Optional[str] = None) -> None:
    """Creates and migrates the schema, retrying on lock conflicts."""
    from loguru import logger

    letzter: Exception | None = None
    for versuch in range(1, _MIGRATION_ATTEMPTS + 1):
        try:
            _init_db(admin_email)
            if versuch > 1:
                logger.info("Datenbank-Wanderung im {}. Anlauf durch", versuch)
            return
        except (psycopg2.errors.DeadlockDetected, psycopg2.errors.LockNotAvailable) as e:
            letzter = e
            logger.warning(
                "Datenbank-Wanderung: Sperrkonflikt im {}. Anlauf, neuer Versuch in {}s "
                "({})", versuch, versuch, type(e).__name__,
            )
            import time
            time.sleep(versuch)
    raise letzter  # type: ignore[misc]


def _init_db(admin_email: Optional[str] = None) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Bounds every single lock in this session, see above.
            cur.execute(f"SET lock_timeout = '{_MIGRATION_LOCK_TIMEOUT}'")
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            # pg_trgm carries the typo tolerant keyword anchor of the search.
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

            # Renames old table prefixes to aia_*.
            for old, new in [
                # Stage 1: very old ki_tutor_* tables migrate straight to aia_*.
                ("ki_tutor_modules", "aia_modules"),
                ("ki_tutor_access_links", "aia_access_links"),
                ("ki_tutor_enrollments", "aia_enrollments"),
                ("ki_tutor_sources", "aia_sources"),
                ("ki_tutor_chunks", "aia_chunks"),
                ("ki_tutor_mindmaps", "aia_mindmaps"),
                ("ki_tutor_data_tables", "aia_data_tables"),
                ("ki_tutor_messages", "aia_messages"),
                ("ki_tutor_user_settings", "aia_user_settings"),
                ("ki_tutor_notes", "aia_notes"),
                ("ki_tutor_glossary_entries", "aia_glossary_entries"),
                ("ki_tutor_exercise_sets", "aia_exercise_sets"),
                ("ki_tutor_exercise_items", "aia_exercise_items"),
                ("ki_tutor_exercise_progress", "aia_exercise_progress"),
                ("ki_tutor_streaks", "aia_streaks"),
                # Stage 2: intermediate kia_* tables migrate to aia_*.
                ("kia_modules", "aia_modules"),
                ("kia_access_links", "aia_access_links"),
                ("kia_enrollments", "aia_enrollments"),
                ("kia_sources", "aia_sources"),
                ("kia_chunks", "aia_chunks"),
                ("kia_mindmaps", "aia_mindmaps"),
                ("kia_data_tables", "aia_data_tables"),
                ("kia_messages", "aia_messages"),
                ("kia_user_settings", "aia_user_settings"),
                ("kia_notes", "aia_notes"),
                ("kia_glossary_entries", "aia_glossary_entries"),
                ("kia_exercise_sets", "aia_exercise_sets"),
                ("kia_exercise_items", "aia_exercise_items"),
                ("kia_exercise_progress", "aia_exercise_progress"),
                ("kia_streaks", "aia_streaks"),
                ("kia_schedule_entries", "aia_schedule_entries"),
                ("kia_schedule_processed_sources", "aia_schedule_processed_sources"),
                ("kia_schedule_jobs", "aia_schedule_jobs"),
                ("kia_llm_usage_log", "aia_llm_usage_log"),
                # Stage 3: rename German "zeitplan" tables (any prefix that survived) to schedule.
                ("kia_zeitplan_entries", "aia_schedule_entries"),
                ("kia_zeitplan_jobs", "aia_schedule_jobs"),
                ("kia_zeitplan_processed_sources", "aia_schedule_processed_sources"),
                # Stage 4: rename aia_module* tables to aia_workspace* (consistency with frontend /workspace route).
                ("aia_modules", "aia_workspaces"),
            ]:
                cur.execute(
                    "SELECT to_regclass(%s) IS NOT NULL AND to_regclass(%s) IS NULL",
                    (f"public.{old}", f"public.{new}"),
                )
                if cur.fetchone()[0]:
                    cur.execute(f"ALTER TABLE {old} RENAME TO {new}")

            # Rename legacy zeitplan indices to schedule (idempotent).
            for old_idx, new_idx in [
                ("idx_zeitplan_module_user", "idx_schedule_workspace_user"),
                ("idx_zeitplan_due_date", "idx_schedule_due_date"),
                ("idx_zeitplan_jobs_module_user", "idx_schedule_jobs_workspace_user"),
                # Stage 4: schedule indices use workspace_user instead of module_user.
                ("idx_schedule_module_user", "idx_schedule_workspace_user"),
                ("idx_schedule_jobs_module_user", "idx_schedule_jobs_workspace_user"),
                ("idx_exercise_sets_module_user", "idx_exercise_sets_workspace_user"),
            ]:
                cur.execute(
                    "SELECT to_regclass(%s) IS NOT NULL AND to_regclass(%s) IS NULL",
                    (f"public.{old_idx}", f"public.{new_idx}"),
                )
                if cur.fetchone()[0]:
                    cur.execute(f"ALTER INDEX {old_idx} RENAME TO {new_idx}")

            # Stage 4: rename module_id columns to workspace_id in dependent tables (idempotent).
            for table in (
                "aia_access_links",
                "aia_enrollments",
                "aia_sources",
                "aia_mindmaps",
                "aia_data_tables",
                "aia_messages",
                "aia_user_settings",
                "aia_notes",
                "aia_exercise_sets",
                "aia_streaks",
                "aia_schedule_entries",
                "aia_schedule_processed_sources",
                "aia_schedule_jobs",
            ):
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = %s
                      AND column_name = 'module_id'
                    """,
                    (table,),
                )
                if cur.fetchone():
                    cur.execute(f"ALTER TABLE {table} RENAME COLUMN module_id TO workspace_id")

            # Stage 4: rename unique constraints that referenced module_id (idempotent).
            for table, old_constraint, new_constraint in [
                ("aia_enrollments", "aia_enrollments_module_id_user_id_link_id_key",
                 "aia_enrollments_workspace_id_user_id_link_id_key"),
                ("aia_user_settings", "aia_user_settings_module_id_user_id_key",
                 "aia_user_settings_workspace_id_user_id_key"),
                ("aia_streaks", "aia_streaks_module_id_user_id_key",
                 "aia_streaks_workspace_id_user_id_key"),
            ]:
                cur.execute(
                    "SELECT 1 FROM pg_constraint WHERE conname = %s",
                    (old_constraint,),
                )
                if cur.fetchone():
                    cur.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old_constraint} TO {new_constraint}")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            SERIAL PRIMARY KEY,
                    username      TEXT NOT NULL UNIQUE,
                    display_name  TEXT NOT NULL,
                    email         TEXT,
                    active        INTEGER NOT NULL DEFAULT 1,
                    role          TEXT NOT NULL DEFAULT 'lecturer',
                    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Accounts live in the database since LDAP was switched off, so the login name drops its LDAP prefix (idempotent).
            cur.execute("""
                SELECT
                    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                           AND table_name = 'users' AND column_name = 'ldap_username'),
                    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                           AND table_name = 'users' AND column_name = 'username')
            """)
            alt_da, neu_da = cur.fetchone()
            if alt_da and not neu_da:
                cur.execute("ALTER TABLE users RENAME COLUMN ldap_username TO username")
            cur.execute("SELECT 1 FROM pg_constraint WHERE conname = 'users_ldap_username_key'")
            if cur.fetchone():
                cur.execute("ALTER TABLE users RENAME CONSTRAINT users_ldap_username_key TO users_username_key")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'lecturer'")
            # The login checks against this column, NULL means no form login for this account.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT")
            # Chat block after burst-limit trigger (survives backend restart, unlike Redis counter).
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_blocked_until TIMESTAMP WITH TIME ZONE")
            # Interface language wish, shared across devices after login.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS locale TEXT NOT NULL DEFAULT 'de' CHECK (locale IN ('de', 'en'))")
            # Language level assessment, NULL means not done yet.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS language_level TEXT CHECK (language_level IN ('A1','A2','B1','B2','C1','C2'))")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS language_level_set_at TIMESTAMP WITH TIME ZONE")
            # Where the level came from, the test or the person's own choice.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS language_level_source TEXT CHECK (language_level_source IN ('test','self'))")
            # The one language trainer switch, per person since 2026-09.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS language_training_active BOOLEAN NOT NULL DEFAULT FALSE")
            # NULL means the start question is still due.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS language_training_asked_at TIMESTAMP WITH TIME ZONE")
            # Demo account: its active courses appear on everyone's start page.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT FALSE")
            # Tour: tied to the account, not the browser, else every device starts over.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tour_seen_at TIMESTAMP")
            # Own interfaces: when and which version of the disclaimer the person accepted.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS interfaces_consent_at TIMESTAMP WITH TIME ZONE")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS interfaces_consent_version INTEGER")
            # Global AI/privacy notice at first login, same for TH account, external access and demo.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS global_consent_at TIMESTAMP WITH TIME ZONE")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS global_consent_version INTEGER")
            # The tools tour is gone, the tile overview explains every tool itself.
            cur.execute("ALTER TABLE users DROP COLUMN IF EXISTS tools_tour_seen_at")
            # The single mark per account is gone, aia_demo_seeded remembers per module.
            cur.execute("ALTER TABLE users DROP COLUMN IF EXISTS demo_seeded_at")
            # The five single marks are gone, only the final value stays.
            cur.execute("ALTER TABLE users DROP COLUMN IF EXISTS language_level_skill_scores")
            # The level list walks the whole ladder again, old B1+ becomes B2.
            cur.execute("UPDATE users SET language_level = 'B2' WHERE language_level = 'B1+'")
            cur.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_language_level_check")
            cur.execute("ALTER TABLE users ADD CONSTRAINT users_language_level_check CHECK (language_level IN ('A1','A2','B1','B2','C1','C2'))")
            # Roles: fixed system roles plus custom roles with permission keys.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS custom_roles (
                    id            SERIAL PRIMARY KEY,
                    name          TEXT NOT NULL UNIQUE,
                    permissions   JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute(
                "ALTER TABLE custom_roles ADD COLUMN IF NOT EXISTS permissions "
                "JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
            # Old migration: allow_aia became the three-valued aia_access.
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'custom_roles'
                          AND column_name = 'allow_aia'
                    ) THEN
                        ALTER TABLE custom_roles ADD COLUMN IF NOT EXISTS aia_access
                            TEXT NOT NULL DEFAULT 'none';
                        UPDATE custom_roles SET aia_access = 'read' WHERE allow_aia = TRUE;
                        ALTER TABLE custom_roles DROP COLUMN allow_aia;
                    END IF;
                END $$;
            """)
            # New migration: aia_access and allowed_tools become permission keys.
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'custom_roles'
                          AND column_name = 'allowed_tools'
                    ) THEN
                        UPDATE custom_roles SET permissions = (
                            SELECT COALESCE(jsonb_agg(k), '[]'::jsonb) FROM (
                                SELECT 'aia.use'::text AS k
                                UNION ALL
                                SELECT 'aia.workspace.create'
                                    WHERE COALESCE(custom_roles.aia_access, '') = 'edit'
                                UNION ALL
                                SELECT 'tools.' || value
                                    FROM jsonb_array_elements_text(custom_roles.allowed_tools)
                            ) AS m
                        )
                        WHERE permissions = '[]'::jsonb;
                        ALTER TABLE custom_roles DROP COLUMN allowed_tools;
                        ALTER TABLE custom_roles DROP COLUMN IF EXISTS aia_access;
                    END IF;
                END $$;
            """)
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS custom_role_id INTEGER "
                "REFERENCES custom_roles(id) ON DELETE SET NULL"
            )
            # Migrate legacy role strings (idempotent).
            cur.execute("UPDATE users SET role = 'staff' WHERE role = 'lecturer'")
            cur.execute("UPDATE users SET role = 'user'  WHERE role = 'student'")
            # New default for the column going forward.
            cur.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'user'")
            # Constraint: role must be one of the four allowed values.
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'users_role_check'
                    ) THEN
                        ALTER TABLE users
                            ADD CONSTRAINT users_role_check
                            CHECK (role IN ('admin', 'staff', 'user', 'custom'));
                    END IF;
                END
                $$
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    id         SERIAL PRIMARY KEY,
                    email      TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Invitations are the access path without SSO and go away with it.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS invites (
                    id             SERIAL PRIMARY KEY,
                    token          TEXT NOT NULL UNIQUE,
                    email          TEXT NOT NULL,
                    uid            TEXT NOT NULL,
                    role           TEXT NOT NULL DEFAULT 'user',
                    custom_role_id INTEGER,
                    created_by     INTEGER,
                    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                    expires_at     TIMESTAMP NOT NULL,
                    used_at        TIMESTAMP
                )
            """)
            # The inviter may disappear, the invitation stays.
            cur.execute("ALTER TABLE invites ALTER COLUMN created_by DROP NOT NULL")
            # An invitation without a mail address is normal, the login name is enough.
            cur.execute("ALTER TABLE invites ALTER COLUMN email DROP NOT NULL")
            cur.execute("CREATE INDEX IF NOT EXISTS invites_email_idx ON invites (LOWER(email))")
            # A reset link keeps the old password until the person sets a new one, only the hash of the key is stored.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id          SERIAL PRIMARY KEY,
                    token_hash  TEXT NOT NULL UNIQUE,
                    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_by  INTEGER,
                    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                    expires_at  TIMESTAMP NOT NULL,
                    used_at     TIMESTAMP
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS password_reset_tokens_user_idx ON password_reset_tokens (user_id)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS access_codes (
                    id             SERIAL PRIMARY KEY,
                    code           TEXT NOT NULL UNIQUE,
                    label          TEXT NOT NULL,
                    role           TEXT NOT NULL DEFAULT 'user',
                    custom_role_id INTEGER,
                    max_uses       INTEGER NOT NULL,
                    used_count     INTEGER NOT NULL DEFAULT 0,
                    valid_until    TIMESTAMP NOT NULL,
                    access_hours      INTEGER DEFAULT 336,
                    show_credentials  BOOLEAN NOT NULL DEFAULT TRUE,
                    show_evaluation   BOOLEAN NOT NULL DEFAULT FALSE,
                    active         BOOLEAN NOT NULL DEFAULT TRUE,
                    created_by     INTEGER,
                    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Interpreter: one conversation per row, every sentence in both languages.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS interpreter_sessions (
                    id          TEXT PRIMARY KEY,
                    owner_id    INTEGER NOT NULL,
                    left_lang   TEXT NOT NULL DEFAULT 'DE',
                    right_lang  TEXT NOT NULL DEFAULT 'EN-US',
                    left_name   TEXT NOT NULL DEFAULT '',
                    right_name  TEXT NOT NULL DEFAULT '',
                    ended_at    TIMESTAMP,
                    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS interpreter_turns (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL REFERENCES interpreter_sessions(id) ON DELETE CASCADE,
                    side        TEXT NOT NULL,
                    source      TEXT NOT NULL DEFAULT 'spoken',
                    original    TEXT NOT NULL,
                    translation TEXT NOT NULL DEFAULT '',
                    status      TEXT NOT NULL DEFAULT 'done',
                    edited      BOOLEAN NOT NULL DEFAULT FALSE,
                    at          BIGINT NOT NULL,
                    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_interpreter_turns_session ON interpreter_turns (session_id, at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_interpreter_sessions_owner ON interpreter_sessions (owner_id, updated_at DESC)")
            # Older installs still carry the day-based column, rename and convert it in
            # place so a code that read "14 Tage" keeps meaning the same span, now in hours.
            cur.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'access_codes'
                  AND column_name = 'access_days'
            """)
            if cur.fetchone():
                cur.execute("ALTER TABLE access_codes RENAME COLUMN access_days TO access_hours")
                cur.execute(
                    "UPDATE access_codes SET access_hours = access_hours * 24 "
                    "WHERE access_hours IS NOT NULL"
                )
            cur.execute(
                "ALTER TABLE access_codes ADD COLUMN IF NOT EXISTS "
                "show_credentials BOOLEAN NOT NULL DEFAULT TRUE"
            )
            # Off by default, an existing code must not start showing the evaluation.
            cur.execute(
                "ALTER TABLE access_codes ADD COLUMN IF NOT EXISTS "
                "show_evaluation BOOLEAN NOT NULL DEFAULT FALSE"
            )
            # NULL means the accounts this code creates never expire.
            cur.execute("ALTER TABLE access_codes ALTER COLUMN access_hours DROP NOT NULL")
            # A test access runs out on its own, the two columns stay empty for everyone else.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS access_expires_at TIMESTAMP")
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS access_code_id INTEGER "
                "REFERENCES access_codes(id) ON DELETE SET NULL"
            )
            # Who was in whose account when, the record for data protection.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS impersonation_log (
                    id              SERIAL PRIMARY KEY,
                    actor_user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    actor_username  TEXT NOT NULL,
                    target_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    target_username TEXT NOT NULL,
                    started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
                    ended_at        TIMESTAMP,
                    ended_reason    TEXT
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS impersonation_log_started_idx "
                "ON impersonation_log (started_at DESC)"
            )
            # Anonymous by design, no link to the reporting account is stored unless the person opts in.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id         SERIAL PRIMARY KEY,
                    category   TEXT NOT NULL,
                    message    TEXT NOT NULL,
                    contact    TEXT,
                    username   TEXT,
                    page_path  TEXT,
                    status     TEXT NOT NULL DEFAULT 'open',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS username TEXT")
            cur.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open'")
            # One-time move from the old done flag to the three-way status.
            cur.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'feedback' AND column_name = 'done'
            """)
            if cur.fetchone():
                cur.execute("UPDATE feedback SET status = 'done' WHERE done")
                cur.execute("ALTER TABLE feedback DROP COLUMN done")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS feedback_created_idx ON feedback (created_at DESC)"
            )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback_attachments (
                    id            SERIAL PRIMARY KEY,
                    feedback_id   INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
                    filename      TEXT NOT NULL,
                    content_type  TEXT NOT NULL,
                    size_bytes    INTEGER NOT NULL,
                    storage_key   TEXT NOT NULL,
                    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS feedback_attachments_feedback_idx "
                "ON feedback_attachments (feedback_id)"
            )
            # The evaluation itself lives in settings as key/value, only the answers need a table.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS evaluation_responses (
                    id         SERIAL PRIMARY KEY,
                    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    answers    JSONB NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS evaluation_responses_user_idx "
                "ON evaluation_responses (user_id)"
            )
            # Stamps of anonymous event visitors, only the hash of the browser's id is kept.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS event_stamps (
                    visitor_hash TEXT NOT NULL,
                    station_id   TEXT NOT NULL,
                    stamped_at   TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (visitor_hash, station_id)
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS event_stamps_station_idx ON event_stamps (station_id)"
            )
            # One short code per visitor, made on first use, lets staff find a visitor's card to reset it.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS event_visitor_codes (
                    visitor_hash TEXT PRIMARY KEY,
                    code         TEXT NOT NULL UNIQUE
                )
            """)
            # Ticks of the event task card, one per account and task.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS event_tasks (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL,
                    done_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, task_id)
                )
            """)
            # Raffle entries of visitors with a full card, the address is the only personal datum kept.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS event_raffle_entries (
                    id           SERIAL PRIMARY KEY,
                    visitor_hash TEXT NOT NULL UNIQUE,
                    email        TEXT NOT NULL UNIQUE,
                    entered_at   TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id                  SERIAL PRIMARY KEY,
                    job_uuid            TEXT NOT NULL UNIQUE,
                    user_id             INTEGER NOT NULL DEFAULT 0,
                    tool                TEXT NOT NULL,
                    original_filename   TEXT NOT NULL DEFAULT '',
                    input_path          TEXT,
                    result_path         TEXT,
                    result_filename     TEXT,
                    status              TEXT NOT NULL DEFAULT 'pending',
                    error_message       TEXT,
                    progress            TEXT,
                    celery_task_id      TEXT,
                    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
                    started_at          TIMESTAMP,
                    completed_at        TIMESTAMP,
                    expires_at          TIMESTAMP,
                    progress_updated_at TIMESTAMP,
                    render_started_at   TIMESTAMP,
                    render_queued_at    TIMESTAMP,
                    attempts            INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at     TIMESTAMP
                )
            """)
            cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS render_queued_at TIMESTAMP")
            # How often a failed stage already resumed by itself, and when the next try is due.
            cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0")
            cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMP")
            # The supervisor asks for due and stuck jobs every few seconds.
            cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status)")

            # Counters for the statistics, one row per day, hour, tool and outcome.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS job_counts (
                    day       DATE     NOT NULL,
                    hour      SMALLINT NOT NULL,
                    tool      TEXT     NOT NULL,
                    status    TEXT     NOT NULL,
                    runs      INTEGER  NOT NULL DEFAULT 0,
                    seconds   BIGINT   NOT NULL DEFAULT 0,
                    PRIMARY KEY (day, hour, tool, status)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_job_counts_day
                ON job_counts(day)
            """)

            # Who was here when, one row per user and hour.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_presence (
                    user_id INTEGER  NOT NULL,
                    day     DATE     NOT NULL,
                    hour    SMALLINT NOT NULL,
                    PRIMARY KEY (user_id, day, hour)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_presence_day
                ON user_presence(day)
            """)

            # Backfills once what is still in jobs.
            if _table_exists(cur, "settings"):
                cur.execute("SELECT value FROM settings WHERE key = 'job_counts_backfill_done'")
                nachtragen = not cur.fetchone()
            else:
                nachtragen = False
            if nachtragen:
                cur.execute("""
                    INSERT INTO job_counts (day, hour, tool, status, runs, seconds)
                    SELECT (completed_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Berlin')::date,
                           EXTRACT(HOUR FROM (completed_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Berlin')),
                           tool, status, COUNT(*),
                           COALESCE(SUM(GREATEST(0, EXTRACT(EPOCH FROM (completed_at - COALESCE(
                               CASE WHEN tool IN ('screencast_render', 'screencast_translate')
                                    THEN render_started_at END,
                               started_at, completed_at)))))::bigint, 0)
                    FROM jobs
                    WHERE status IN ('success', 'failed') AND completed_at IS NOT NULL
                    GROUP BY 1, 2, tool, status
                    ON CONFLICT (day, hour, tool, status) DO NOTHING
                """)
                cur.execute(
                    """INSERT INTO settings (key, value) VALUES ('job_counts_backfill_done', 'true')
                       ON CONFLICT (key) DO UPDATE SET value = 'true'"""
                )

            # The same for the created row, also exactly once.
            if _table_exists(cur, "settings"):
                cur.execute("SELECT value FROM settings WHERE key = 'job_counts_started_backfill_done'")
                nachtragen = not cur.fetchone()
            else:
                nachtragen = False
            if nachtragen:
                cur.execute("""
                    INSERT INTO job_counts (day, hour, tool, status, runs, seconds)
                    SELECT (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Berlin')::date,
                           EXTRACT(HOUR FROM (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Berlin')),
                           tool, 'started', COUNT(*), 0
                    FROM jobs
                    GROUP BY 1, 2, tool
                    ON CONFLICT (day, hour, tool, status) DO NOTHING
                """)
                cur.execute(
                    """INSERT INTO settings (key, value) VALUES ('job_counts_started_backfill_done', 'true')
                       ON CONFLICT (key) DO UPDATE SET value = 'true'"""
                )
            cur.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS username")
            # Language at creation time so workers without an HTTP context can translate errors.
            cur.execute(
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS creator_locale TEXT NOT NULL DEFAULT 'de' "
                "CHECK (creator_locale IN ('de', 'en'))"
            )
            # The deadline is gone, only the pool of recent jobs counts now.
            cur.execute("UPDATE jobs SET expires_at = NULL WHERE expires_at IS NOT NULL")
            # A page keeps its link when it is switched off and on again, the row goes with the page.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS page_shares (
                    job_uuid   TEXT PRIMARY KEY REFERENCES jobs(job_uuid) ON DELETE CASCADE,
                    user_id    INTEGER NOT NULL,
                    code       TEXT NOT NULL UNIQUE,
                    enabled    BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_page_shares_user ON page_shares (user_id)")
            # A shared page opens for anyone holding the link only when its owner says so.
            cur.execute("ALTER TABLE page_shares ADD COLUMN IF NOT EXISTS public BOOLEAN NOT NULL DEFAULT FALSE")
            # One fixed link per person that lists every page they share.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS page_collections (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    code    TEXT NOT NULL UNIQUE
                )
            """)
            # The collection link opens for others only once its owner shares it.
            cur.execute("ALTER TABLE page_collections ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT FALSE")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id         SERIAL PRIMARY KEY,
                    key        TEXT NOT NULL UNIQUE,
                    value      TEXT NOT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_quotas (
                    id                SERIAL PRIMARY KEY,
                    user_id           INTEGER NOT NULL,
                    quota_type        TEXT NOT NULL,
                    used              INTEGER NOT NULL DEFAULT 0,
                    window_started_at TIMESTAMP,
                    reset_at          TIMESTAMP,
                    updated_at        TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE (user_id, quota_type)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_quota_overrides (
                    id          SERIAL PRIMARY KEY,
                    user_id     INTEGER NOT NULL,
                    quota_type  TEXT NOT NULL,
                    limit_value INTEGER NOT NULL,
                    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE (user_id, quota_type)
                )
            """)
            # Every tool has its own window in user_quotas.
            cur.execute("DROP TABLE IF EXISTS user_quota_resets")
            # Per-user terminology lists for translation.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_glossaries (
                    id         TEXT PRIMARY KEY,
                    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name       TEXT NOT NULL,
                    entries    JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_glossaries_user "
                "ON user_glossaries(user_id, created_at)"
            )
            # Saved slide templates of a person, the file itself lives in storage.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS praesentation_vorlagen (
                    id           TEXT PRIMARY KEY,
                    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name         TEXT NOT NULL,
                    stiltext     TEXT NOT NULL DEFAULT '',
                    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    last_used_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_praesentation_vorlagen_user "
                "ON praesentation_vorlagen(user_id, created_at)"
            )
            if admin_email and admin_email.strip():
                cur.execute(
                    "INSERT INTO whitelist (email) VALUES (%s) ON CONFLICT DO NOTHING",
                    (admin_email.strip().lower(),),
                )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_workspaces (
                    id                   SERIAL PRIMARY KEY,
                    uuid                 TEXT NOT NULL UNIQUE,
                    user_id              INTEGER NOT NULL,
                    title                TEXT NOT NULL,
                    description          TEXT,
                    is_active            BOOLEAN NOT NULL DEFAULT FALSE,
                    status               TEXT NOT NULL DEFAULT 'pending',
                    enroll_code          TEXT UNIQUE,
                    enroll_code_expires  TIMESTAMP,
                    embedding_model      TEXT NOT NULL DEFAULT '',
                    embedding_fingerprint TEXT,
                    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at           TIMESTAMP NOT NULL DEFAULT NOW(),
                    last_visited_at      TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Migration: add last_visited_at; backfill existing rows from updated_at so initial sort is meaningful
            cur.execute("ALTER TABLE aia_workspaces ADD COLUMN IF NOT EXISTS last_visited_at TIMESTAMP")
            cur.execute("UPDATE aia_workspaces SET last_visited_at = COALESCE(updated_at, created_at, NOW()) WHERE last_visited_at IS NULL")
            cur.execute("ALTER TABLE aia_workspaces ALTER COLUMN last_visited_at SET NOT NULL")
            cur.execute("ALTER TABLE aia_workspaces ALTER COLUMN last_visited_at SET DEFAULT NOW()")
            # The one language the course room translates its transcripts into.
            cur.execute(
                "ALTER TABLE aia_workspaces ADD COLUMN IF NOT EXISTS transcript_target_lang TEXT NOT NULL DEFAULT 'en'"
            )
            # The language the assessment is conducted in.
            cur.execute(
                "ALTER TABLE aia_workspaces ADD COLUMN IF NOT EXISTS diagnosis_language TEXT NOT NULL DEFAULT 'de'"
            )
            # The trainer hangs on the person since 2026-09, the course switch is gone.
            cur.execute("ALTER TABLE aia_workspaces DROP COLUMN IF EXISTS language_training_active")
            # The one demo course the guided tour runs in, its stations point at that course's files.
            cur.execute(
                "ALTER TABLE aia_workspaces ADD COLUMN IF NOT EXISTS is_tour_module BOOLEAN NOT NULL DEFAULT FALSE"
            )
            # Owner-managed pinned note shown above the sources list. Plain text + structured links.
            cur.execute(
                "ALTER TABLE aia_workspaces ADD COLUMN IF NOT EXISTS staff_note_text TEXT"
            )
            cur.execute(
                "ALTER TABLE aia_workspaces ADD COLUMN IF NOT EXISTS staff_note_links JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
            # Filter for the grammar catalogue, dropped again.
            cur.execute("ALTER TABLE aia_workspaces DROP COLUMN IF EXISTS grammar_types")
            # Old summary switch, gone together with the summaries.
            cur.execute("ALTER TABLE aia_workspaces DROP COLUMN IF EXISTS summary_mode")
            # Old translation mode, translating now always happens on click.
            cur.execute("ALTER TABLE aia_workspaces DROP COLUMN IF EXISTS transcript_translation_mode")
            # The podcast filed its uploads in a hidden module, it reads them whole now.
            cur.execute("ALTER TABLE aia_workspaces DROP COLUMN IF EXISTS is_podcast_store")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_access_links (
                    id           SERIAL PRIMARY KEY,
                    workspace_id INTEGER NOT NULL
                                   REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    code         TEXT NOT NULL UNIQUE,
                    expires_at   TIMESTAMP,
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_enrollments (
                    id             SERIAL PRIMARY KEY,
                    workspace_id   INTEGER NOT NULL
                                     REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id        INTEGER NOT NULL,
                    link_id        INTEGER REFERENCES aia_access_links(id) ON DELETE SET NULL,
                    enrolled_until TIMESTAMP,
                    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                    role           TEXT NOT NULL DEFAULT 'student',
                    UNIQUE (workspace_id, user_id)
                )
            """)
            # Migration: add link_id column if table already existed without it
            cur.execute("ALTER TABLE aia_enrollments ADD COLUMN IF NOT EXISTS link_id INTEGER REFERENCES aia_access_links(id) ON DELETE SET NULL")
            # Joined through the demo, so exactly these enrollments can be cleared.
            cur.execute("ALTER TABLE aia_enrollments ADD COLUMN IF NOT EXISTS via_demo BOOLEAN NOT NULL DEFAULT FALSE")
            # The role sits on the enrollment, never on the link.
            cur.execute(
                "ALTER TABLE aia_enrollments ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'student'"
            )
            # Per-user marker, independent of access type (owner, tutor or student).
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_workspace_favorites (
                    user_id      INTEGER NOT NULL,
                    workspace_id INTEGER NOT NULL
                                   REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, workspace_id)
                )
            """)
            # Calendar colour per person and workspace, private appointments under their own key.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_calendar_colors (
                    user_id   INTEGER NOT NULL,
                    group_key TEXT NOT NULL,
                    color     INTEGER NOT NULL,
                    PRIMARY KEY (user_id, group_key)
                )
            """)
            # Workspaces an access code enrolls its accounts into, always as learners.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS access_code_workspaces (
                    code_id      INTEGER NOT NULL REFERENCES access_codes(id) ON DELETE CASCADE,
                    workspace_id INTEGER NOT NULL REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    PRIMARY KEY (code_id, workspace_id)
                )
            """)
            cur.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'aia_enrollments_role_check'
                    ) THEN
                        ALTER TABLE aia_enrollments
                            ADD CONSTRAINT aia_enrollments_role_check
                            CHECK (role IN ('student', 'tutor'));
                    END IF;
                END $$
            """)
            # Links never carried a role in a released version; drop the short-lived column.
            cur.execute("ALTER TABLE aia_access_links DROP CONSTRAINT IF EXISTS aia_access_links_role_check")
            cur.execute("ALTER TABLE aia_access_links DROP COLUMN IF EXISTS role")
            # Migration: drop legacy unique constraints (both pre-link_id and pre-workspace_id versions)
            cur.execute("""
                DO $$ BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'aia_enrollments_module_id_user_id_key'
                    ) THEN
                        ALTER TABLE aia_enrollments
                            DROP CONSTRAINT aia_enrollments_module_id_user_id_key;
                    END IF;
                END $$
            """)
            # One enrollment per person and course room, existing duplicates are merged first.
            cur.execute("""
                UPDATE aia_enrollments k
                SET role = 'tutor'
                FROM aia_enrollments t
                WHERE t.workspace_id = k.workspace_id
                  AND t.user_id = k.user_id
                  AND t.role = 'tutor'
                  AND k.role <> 'tutor'
            """)
            # On an empty database there are no messages to move.
            if _table_exists(cur, "aia_messages"):
                cur.execute("""
                    UPDATE aia_messages m
                    SET enrollment_id = behalten.id
                    FROM aia_enrollments e
                    JOIN (
                        SELECT DISTINCT ON (workspace_id, user_id) id, workspace_id, user_id
                        FROM aia_enrollments
                        ORDER BY workspace_id, user_id, created_at, id
                    ) behalten
                      ON behalten.workspace_id = e.workspace_id
                     AND behalten.user_id = e.user_id
                    WHERE m.enrollment_id = e.id
                      AND e.id <> behalten.id
                """)
            cur.execute("""
                DELETE FROM aia_enrollments e
                USING (
                    SELECT DISTINCT ON (workspace_id, user_id) id, workspace_id, user_id
                    FROM aia_enrollments
                    ORDER BY workspace_id, user_id, created_at, id
                ) behalten
                WHERE e.workspace_id = behalten.workspace_id
                  AND e.user_id = behalten.user_id
                  AND e.id <> behalten.id
            """)
            cur.execute(
                "ALTER TABLE aia_enrollments "
                "DROP CONSTRAINT IF EXISTS aia_enrollments_workspace_id_user_id_link_id_key"
            )
            cur.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'aia_enrollments_workspace_id_user_id_key'
                    ) THEN
                        ALTER TABLE aia_enrollments
                            ADD CONSTRAINT aia_enrollments_workspace_id_user_id_key
                            UNIQUE (workspace_id, user_id);
                    END IF;
                END $$
            """)
            # Migration: migrate existing enroll_code from workspaces to access_links
            cur.execute("""
                INSERT INTO aia_access_links (workspace_id, code, expires_at)
                SELECT id, enroll_code, enroll_code_expires
                FROM aia_workspaces
                WHERE enroll_code IS NOT NULL
                  AND enroll_code_expires IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM aia_access_links al
                      WHERE al.code = aia_workspaces.enroll_code
                  )
            """)
            # Migration: link existing enrollments to their access_links
            cur.execute("""
                UPDATE aia_enrollments e
                SET link_id = al.id
                FROM aia_access_links al
                JOIN aia_workspaces m ON m.id = al.workspace_id
                WHERE e.workspace_id = m.id
                  AND al.code = m.enroll_code
                  AND e.link_id IS NULL
            """)
            # Migration: allow NULL expires_at in access_links
            cur.execute("ALTER TABLE aia_access_links ALTER COLUMN expires_at DROP NOT NULL")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_sources (
                    id              SERIAL PRIMARY KEY,
                    uuid            TEXT NOT NULL UNIQUE,
                    workspace_id    INTEGER NOT NULL
                                      REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    filename        TEXT NOT NULL,
                    file_path       TEXT NOT NULL,
                    file_type       TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    chunk_count     INTEGER NOT NULL DEFAULT 0,
                    embedding_model TEXT NOT NULL DEFAULT '',
                    toc             JSONB,
                    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Migration: add toc column if missing
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS toc JSONB
            """)
            # Migration: add duration column for audio/video sources
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS duration REAL
            """)
            # Migration: add error_message column for failed sources
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS error_message TEXT
            """)
            # Migration: add language column (Whisper-detected source language, e.g. 'de', 'en')
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS language TEXT
            """)
            # Fine-grained ingest progress, NULL when the source is idle.
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS progress JSONB
            """)
            # How text recognition went, NULL when there was no candidate page.
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS ocr_info JSONB
            """)
            # A short summary per source, built during ingest.
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS summary TEXT
            """)
            # The link a web page source came from, NULL for uploaded files.
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS source_url TEXT
            """)
            # Content hash of the uploaded file, so the podcast store recognises a re-upload.
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS content_hash TEXT
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_aia_sources_workspace_hash
                ON aia_sources (workspace_id, content_hash)
            """)
            # Last run that used this source, the podcast store evicts by this.
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP NOT NULL DEFAULT NOW()
            """)
            # Chapters structure the source list but decide nothing about the chat.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_chapters (
                    id           SERIAL PRIMARY KEY,
                    uuid         TEXT NOT NULL UNIQUE,
                    workspace_id INTEGER NOT NULL
                                   REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    name         TEXT NOT NULL,
                    position     INTEGER NOT NULL DEFAULT 0,
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_aia_chapters_workspace
                ON aia_chapters (workspace_id, position)
            """)
            # SET NULL instead of CASCADE, a deleted chapter takes no source with it.
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS chapter_id INTEGER
                    REFERENCES aia_chapters(id) ON DELETE SET NULL
            """)
            # Manual order within a chapter, NULL keeps the newest on top.
            cur.execute("""
                ALTER TABLE aia_sources ADD COLUMN IF NOT EXISTS position INTEGER
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_chunks (
                    id          SERIAL PRIMARY KEY,
                    source_id   INTEGER NOT NULL
                                  REFERENCES aia_sources(id) ON DELETE CASCADE,
                    page_number INTEGER NOT NULL,
                    content     TEXT NOT NULL,
                    embedding   vector,
                    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Migration: drop fixed-dimension constraint so any embedding model can be used
            _drop_embedding_dimension_once(cur)
            # Migration: add start_time/end_time for audio/video chunks
            cur.execute("""
                ALTER TABLE aia_chunks ADD COLUMN IF NOT EXISTS start_time REAL
            """)
            cur.execute("""
                ALTER TABLE aia_chunks ADD COLUMN IF NOT EXISTS end_time REAL
            """)
            # Hybrid Search: tsvector column for BM25-style keyword search
            cur.execute("""
                ALTER TABLE aia_chunks
                    ADD COLUMN IF NOT EXISTS search_vector tsvector
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_search
                ON aia_chunks USING gin(search_vector)
            """)
            # Trigram index for the typo tolerant keyword search.
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm
                ON aia_chunks USING gin(content gin_trgm_ops)
            """)
            # Source plus page for the evidence search, source_id first because of media sources.
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_source_page
                ON aia_chunks (source_id, page_number)
            """)
            # The old page and paragraph summaries are gone.
            cur.execute("DROP TABLE IF EXISTS aia_page_summaries")
            cur.execute("DROP TABLE IF EXISTS aia_paragraph_summaries")
            cur.execute("ALTER TABLE aia_sources DROP COLUMN IF EXISTS summaries_status")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_mindmaps (
                    id           SERIAL PRIMARY KEY,
                    workspace_id INTEGER NOT NULL
                                   REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id      INTEGER NOT NULL,
                    source_ids   JSONB NOT NULL,
                    status       TEXT NOT NULL DEFAULT 'pending',
                    mindmap      JSONB,
                    error        TEXT,
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_data_tables (
                    id           SERIAL PRIMARY KEY,
                    workspace_id INTEGER NOT NULL
                                   REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id      INTEGER NOT NULL,
                    source_ids   JSONB NOT NULL,
                    status       TEXT NOT NULL DEFAULT 'pending',
                    title        TEXT,
                    table_data   JSONB,
                    sources      JSONB,
                    error        TEXT,
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Separate queue for the assistant's background work.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_jobs (
                    id             SERIAL PRIMARY KEY,
                    job_uuid       TEXT NOT NULL UNIQUE,
                    user_id        INTEGER NOT NULL,
                    area           TEXT NOT NULL,
                    task_name      TEXT NOT NULL,
                    payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
                    status         TEXT NOT NULL DEFAULT 'queued',
                    celery_task_id TEXT,
                    error          TEXT,
                    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                    started_at     TIMESTAMP,
                    finished_at    TIMESTAMP
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_aia_jobs_area_status "
                "ON aia_jobs(area, status, created_at)"
            )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_messages (
                    id           SERIAL PRIMARY KEY,
                    workspace_id INTEGER NOT NULL
                                   REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id      INTEGER NOT NULL,
                    role         TEXT NOT NULL,
                    content      TEXT NOT NULL,
                    source_pages JSONB,
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Migration: add enrollment_id to messages for per-link scoping
            cur.execute("ALTER TABLE aia_messages ADD COLUMN IF NOT EXISTS enrollment_id INTEGER REFERENCES aia_enrollments(id) ON DELETE SET NULL")
            # Migration: add source_qmap (Q-number → source UUID mapping) to messages
            cur.execute("ALTER TABLE aia_messages ADD COLUMN IF NOT EXISTS source_qmap JSONB")
            # Migration: mark assistant messages whose stream was cancelled by the user
            cur.execute("ALTER TABLE aia_messages ADD COLUMN IF NOT EXISTS aborted BOOLEAN NOT NULL DEFAULT FALSE")
            # Marks answers whose stream died on an error, apart from a cancellation.
            cur.execute("ALTER TABLE aia_messages ADD COLUMN IF NOT EXISTS failed BOOLEAN NOT NULL DEFAULT FALSE")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_user_settings (
                    id                   SERIAL PRIMARY KEY,
                    workspace_id         INTEGER NOT NULL
                                           REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id              INTEGER NOT NULL,
                    chat_lang            TEXT NOT NULL DEFAULT 'de',
                    studio_enabled       BOOLEAN NOT NULL DEFAULT TRUE,
                    UNIQUE (workspace_id, user_id)
                )
            """)
            cur.execute("ALTER TABLE aia_user_settings ADD COLUMN IF NOT EXISTS studio_enabled BOOLEAN NOT NULL DEFAULT TRUE")
            # Target language of the selection bar translation, per person and module.
            cur.execute("ALTER TABLE aia_user_settings ADD COLUMN IF NOT EXISTS popup_translate_lang TEXT NOT NULL DEFAULT 'en'")
            # The personal switch per course is gone, the profile switch replaced it.
            cur.execute("ALTER TABLE aia_user_settings DROP COLUMN IF EXISTS language_training_active")
            cur.execute("ALTER TABLE aia_user_settings DROP COLUMN IF EXISTS sprachtraining_active")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_notes (
                    id           SERIAL PRIMARY KEY,
                    workspace_id INTEGER NOT NULL
                                   REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id      INTEGER NOT NULL,
                    content      TEXT NOT NULL,
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE aia_notes ADD COLUMN IF NOT EXISTS title TEXT")
            cur.execute("ALTER TABLE aia_notes ADD COLUMN IF NOT EXISTS source_uuids JSONB")
            cur.execute("ALTER TABLE aia_notes ADD COLUMN IF NOT EXISTS source_pages JSONB")
            cur.execute("ALTER TABLE aia_notes ADD COLUMN IF NOT EXISTS popup_selection JSONB")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_glossary_entries (
                    id               SERIAL PRIMARY KEY,
                    user_id          INTEGER NOT NULL,
                    source_id        INTEGER NOT NULL
                                       REFERENCES aia_sources(id) ON DELETE CASCADE,
                    term_de          TEXT NOT NULL,
                    term_en          TEXT NOT NULL,
                    definition       TEXT NOT NULL,
                    definition_en    TEXT,
                    example_sentence TEXT,
                    example_sentence_en TEXT,
                    page_number      INTEGER,
                    created_at       TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Migration: add English columns to glossary
            cur.execute("ALTER TABLE aia_glossary_entries ADD COLUMN IF NOT EXISTS definition_en TEXT")
            cur.execute("ALTER TABLE aia_glossary_entries ADD COLUMN IF NOT EXISTS example_sentence_en TEXT")
            # Base form of the marked term, empty when there is none.
            cur.execute("ALTER TABLE aia_glossary_entries ADD COLUMN IF NOT EXISTS base_form TEXT")

            # The glossary is purely personal again, the shared pool goes once.
            cur.execute("""
                SELECT
                  to_regclass('public.aia_user_glossary_picks') IS NOT NULL
                  OR EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_schema = 'public'
                               AND table_name = 'aia_glossary_entries'
                               AND column_name = 'chunk_id')
                  OR NOT EXISTS (SELECT 1 FROM information_schema.columns
                                 WHERE table_schema = 'public'
                                   AND table_name = 'aia_glossary_entries'
                                   AND column_name = 'user_id')
            """)
            if cur.fetchone()[0]:
                cur.execute("DROP TABLE IF EXISTS aia_user_glossary_picks CASCADE")
                cur.execute("TRUNCATE aia_glossary_entries")
                cur.execute("ALTER TABLE aia_glossary_entries DROP COLUMN IF EXISTS chunk_id")
                cur.execute("ALTER TABLE aia_glossary_entries ADD COLUMN IF NOT EXISTS user_id INTEGER")
                cur.execute("ALTER TABLE aia_glossary_entries ALTER COLUMN user_id SET NOT NULL")
                cur.execute("ALTER TABLE aia_chunks DROP COLUMN IF EXISTS glossary_processed")
                cur.execute("DROP INDEX IF EXISTS idx_glossary_source_chunk")
                cur.execute("DROP INDEX IF EXISTS idx_glossary_source")

            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_glossary_user_source "
                "ON aia_glossary_entries(user_id, source_id)"
            )
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_glossary_user_source_term "
                "ON aia_glossary_entries(user_id, source_id, lower(term_de))"
            )
            # ─── Exercise Sets ──────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_exercise_sets (
                    id           SERIAL PRIMARY KEY,
                    workspace_id INTEGER NOT NULL
                                   REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id      INTEGER NOT NULL,
                    tool         TEXT NOT NULL,
                    title        TEXT NOT NULL,
                    mode         TEXT NOT NULL DEFAULT 'glossary',
                    source_uuid  TEXT,
                    card_count   INTEGER NOT NULL DEFAULT 0,
                    status       TEXT NOT NULL DEFAULT 'generating',
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_exercise_items (
                    id          SERIAL PRIMARY KEY,
                    set_id      INTEGER NOT NULL
                                  REFERENCES aia_exercise_sets(id) ON DELETE CASCADE,
                    position    INTEGER NOT NULL DEFAULT 0,
                    front       TEXT NOT NULL,
                    back        TEXT NOT NULL,
                    options     JSONB,
                    correct_idx INTEGER,
                    source_label TEXT,
                    page_number INTEGER,
                    explanation TEXT,
                    start_time  REAL,
                    sources     JSONB
                )
            """)
            # Migration: add sources JSONB to exercise_items
            cur.execute("ALTER TABLE aia_exercise_items ADD COLUMN IF NOT EXISTS sources JSONB")
            # Grammar topics come before the pool, whose topic_id points here.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_grammar_topics (
                    id           SERIAL PRIMARY KEY,
                    workspace_id INTEGER NOT NULL
                                   REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    name         TEXT NOT NULL,
                    created_by   INTEGER,
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Fixed formats of a topic by staff, NULL means all four.
            cur.execute("ALTER TABLE aia_grammar_topics ADD COLUMN IF NOT EXISTS kinds JSONB")
            # One pool per source, tool and level, filled as a by-product of use.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_exercise_pool (
                    id          SERIAL PRIMARY KEY,
                    source_id   INTEGER NOT NULL
                                  REFERENCES aia_sources(id) ON DELETE CASCADE,
                    tool        TEXT NOT NULL,
                    level       TEXT,
                    front       TEXT NOT NULL,
                    back        TEXT NOT NULL,
                    back_en     TEXT,
                    options     JSONB,
                    correct_idx INTEGER,
                    explanation TEXT,
                    source_label TEXT,
                    page_number INTEGER,
                    start_time  REAL,
                    sources     JSONB,
                    extras      JSONB,
                    set_title   TEXT,
                    fingerprint TEXT NOT NULL,
                    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # The pool carries the same fields as an exercise in a set.
            cur.execute("ALTER TABLE aia_exercise_pool ADD COLUMN IF NOT EXISTS back_en TEXT")
            # The grammar exercise also splits by topic, otherwise the column stays empty.
            cur.execute(
                "ALTER TABLE aia_exercise_pool ADD COLUMN IF NOT EXISTS topic_id INTEGER "
                "REFERENCES aia_grammar_topics(id) ON DELETE CASCADE"
            )
            # Presentation format of a grammar exercise, empty otherwise.
            cur.execute("ALTER TABLE aia_exercise_pool ADD COLUMN IF NOT EXISTS kind TEXT")
            # Name of the set this exercise was generated for, so a set drawn purely
            # from the pool gets a title without a model call of its own.
            cur.execute("ALTER TABLE aia_exercise_pool ADD COLUMN IF NOT EXISTS set_title TEXT")
            # COALESCE, because two NULLs do not count as equal in Postgres.
            cur.execute("DROP INDEX IF EXISTS uq_exercise_pool_item")
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_exercise_pool_entry "
                "ON aia_exercise_pool "
                "(source_id, tool, COALESCE(level, ''), COALESCE(topic_id, 0), fingerprint)"
            )
            cur.execute("DROP INDEX IF EXISTS idx_exercise_pool_lookup")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_exercise_pool_find "
                "ON aia_exercise_pool (source_id, tool, level, topic_id)"
            )
            # Fresh generations per pool, it only hands out once enough sets were made.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_exercise_pool_runs (
                    source_id INTEGER NOT NULL
                                REFERENCES aia_sources(id) ON DELETE CASCADE,
                    tool      TEXT NOT NULL,
                    level     TEXT,
                    topic_id  INTEGER REFERENCES aia_grammar_topics(id) ON DELETE CASCADE,
                    runs      INTEGER NOT NULL DEFAULT 0
                )
            """)
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_exercise_pool_runs "
                "ON aia_exercise_pool_runs "
                "(source_id, tool, COALESCE(level, ''), COALESCE(topic_id, 0))"
            )
            # A set points at its pooled exercises instead of copying them.
            cur.execute(
                "ALTER TABLE aia_exercise_items "
                "ADD COLUMN IF NOT EXISTS pool_item_id INTEGER "
                "REFERENCES aia_exercise_pool(id) ON DELETE SET NULL"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_exercise_items_pool "
                "ON aia_exercise_items (pool_item_id)"
            )
            # Listening and reading comprehension is gone, its rows go once.
            cur.execute("DELETE FROM aia_exercise_sets WHERE tool = 'hoerverstehen'")
            cur.execute("DELETE FROM aia_exercise_pool WHERE tool = 'hoerverstehen'")
            # Pool for spoken example sentences, keyed by sentence and voice.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_speech_cache (
                    fingerprint  TEXT PRIMARY KEY,
                    bytes        INTEGER NOT NULL,
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
                    last_used_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # The MP3s now live in storage, the old rows go with the column.
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name = 'aia_speech_cache'
                                 AND column_name = 'audio') THEN
                        DELETE FROM aia_speech_cache;
                    END IF;
                END $$
            """)
            cur.execute("ALTER TABLE aia_speech_cache DROP COLUMN IF EXISTS audio")
            # The nightly cleanup looks for the timestamp.
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_speech_cache_last_used "
                "ON aia_speech_cache (last_used_at)"
            )
            # Remembers per source where the last run stopped, so generation sweeps through.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_context_cursors (
                    workspace_id INTEGER NOT NULL
                                   REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    source_id    INTEGER NOT NULL
                                   REFERENCES aia_sources(id) ON DELETE CASCADE,
                    tool         TEXT NOT NULL,
                    cursors      JSONB NOT NULL,
                    updated_at   TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (workspace_id, source_id, tool)
                )
            """)
            # Remembers per tool which source the next run starts at, so every one gets a turn.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_context_rotation (
                    workspace_id   INTEGER NOT NULL
                                     REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    tool           TEXT NOT NULL,
                    next_source_id INTEGER
                                     REFERENCES aia_sources(id) ON DELETE SET NULL,
                    updated_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (workspace_id, tool)
                )
            """)
            # The separate cloze is gone, its sentences move into the quiz.
            cur.execute(
                "UPDATE aia_exercise_sets SET tool = 'quiz' "
                "WHERE tool IN ('lueckentext', 'vokabeltest')"
            )
            # Grammar sentences carry instruction and pattern pair, topics live in two tables.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_grammar_topic_specs (
                    id        SERIAL PRIMARY KEY,
                    topic_id  INTEGER NOT NULL
                                REFERENCES aia_grammar_topics(id) ON DELETE CASCADE,
                    language  TEXT NOT NULL,
                    rule      TEXT NOT NULL,
                    examples  JSONB NOT NULL DEFAULT '[]'::jsonb,
                    UNIQUE (topic_id, language)
                )
            """)
            # The instruction line per format, worded by the model instead of from a template.
            cur.execute(
                "ALTER TABLE aia_grammar_topic_specs ADD COLUMN IF NOT EXISTS task_lines JSONB"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_grammar_topics_workspace "
                "ON aia_grammar_topics(workspace_id)"
            )
            # Seed for courses from before the topic table, exactly once.
            seed_key = "grammar_topics_seeded"
            cur.execute("SELECT value FROM settings WHERE key = %s", (seed_key,))
            row = cur.fetchone()
            if not (row and row[0] == "true"):
                cur.execute("""
                    INSERT INTO aia_grammar_topics (workspace_id, name, created_by)
                    SELECT w.id, s.name, w.user_id
                    FROM aia_workspaces w
                    CROSS JOIN (VALUES ('Passiv Präsens'), ('Passiv mit Modalverb'),
                                       ('Perfekt'), ('Präteritum'), ('Konjunktiv II'),
                                       ('Relativsätze'), ('Nebensätze'),
                                       ('Adjektivdeklination')) AS s(name)
                    WHERE NOT EXISTS (
                        SELECT 1 FROM aia_grammar_topics t
                        WHERE t.workspace_id = w.id AND t.name = s.name
                    )
                """)
                cur.execute(
                    "INSERT INTO settings (key, value) VALUES (%s, 'true') "
                    "ON CONFLICT (key) DO UPDATE SET value = 'true'",
                    (seed_key,),
                )
            # The old text column pointed nowhere, its sentences come along, only once.
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'aia_exercise_sets' AND column_name = 'grammar_type'"
            )
            if cur.fetchone():
                cur.execute("DELETE FROM aia_exercise_sets WHERE tool = 'grammatik'")
                cur.execute("ALTER TABLE aia_exercise_sets DROP COLUMN grammar_type")
            cur.execute(
                "ALTER TABLE aia_exercise_sets ADD COLUMN IF NOT EXISTS grammar_topic_id "
                "INTEGER REFERENCES aia_grammar_topics(id) ON DELETE SET NULL"
            )
            # Chosen exercise formats as a JSON list, NULL means mixed.
            cur.execute(
                "ALTER TABLE aia_exercise_sets ADD COLUMN IF NOT EXISTS "
                "grammar_kinds JSONB"
            )
            cur.execute("ALTER TABLE aia_exercise_sets ADD COLUMN IF NOT EXISTS instruction TEXT")
            # The person's own instruction to the tool and whether it missed the material.
            cur.execute("ALTER TABLE aia_exercise_sets ADD COLUMN IF NOT EXISTS user_instruction TEXT")
            cur.execute("ALTER TABLE aia_exercise_sets ADD COLUMN IF NOT EXISTS instruction_unmatched BOOLEAN NOT NULL DEFAULT FALSE")
            cur.execute("ALTER TABLE aia_exercise_sets ADD COLUMN IF NOT EXISTS pattern_front TEXT")
            cur.execute("ALTER TABLE aia_exercise_sets ADD COLUMN IF NOT EXISTS pattern_back TEXT")
            # Only the vocabulary cloze fills this, a retry reads it here.
            cur.execute(
                "ALTER TABLE aia_exercise_sets ADD COLUMN IF NOT EXISTS flashcard_set_id "
                "INTEGER REFERENCES aia_exercise_sets(id) ON DELETE SET NULL"
            )
            # All sources of the set in the order they were picked.
            cur.execute("ALTER TABLE aia_exercise_sets DROP COLUMN IF EXISTS source_count")
            cur.execute(
                "ALTER TABLE aia_exercise_sets ADD COLUMN IF NOT EXISTS "
                "source_uuids JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
            # Older sets keep the one source that was recorded.
            cur.execute(
                "UPDATE aia_exercise_sets SET source_uuids = jsonb_build_array(source_uuid) "
                "WHERE source_uuid IS NOT NULL AND source_uuids = '[]'::jsonb"
            )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_exercise_progress (
                    id          SERIAL PRIMARY KEY,
                    set_id      INTEGER NOT NULL
                                  REFERENCES aia_exercise_sets(id) ON DELETE CASCADE,
                    item_id     INTEGER NOT NULL
                                  REFERENCES aia_exercise_items(id) ON DELETE CASCADE,
                    user_id     INTEGER NOT NULL,
                    correct     BOOLEAN NOT NULL,
                    answered_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Every answer carries the number of its round, older ones stay NULL.
            cur.execute(
                "ALTER TABLE aia_exercise_progress "
                "ADD COLUMN IF NOT EXISTS run_no INTEGER"
            )
            # The learner profile is gone, its tables stay until deleted by hand.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_streaks (
                    id              SERIAL PRIMARY KEY,
                    workspace_id    INTEGER NOT NULL
                                      REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id         INTEGER NOT NULL,
                    current_streak  INTEGER NOT NULL DEFAULT 0,
                    max_streak      INTEGER NOT NULL DEFAULT 0,
                    last_active_date DATE,
                    UNIQUE (workspace_id, user_id)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_exercise_sets_workspace_user
                ON aia_exercise_sets(workspace_id, user_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_exercise_items_set
                ON aia_exercise_items(set_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_exercise_progress_set_user
                ON aia_exercise_progress(set_id, user_id)
            """)
            # Migration: add status column if table existed before
            cur.execute("ALTER TABLE aia_exercise_sets ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ready'")
            # Migration: add start_time for audio/video exercise items
            cur.execute("ALTER TABLE aia_exercise_items ADD COLUMN IF NOT EXISTS start_time REAL")
            # Migration: add back_en for bilingual flashcards
            cur.execute("ALTER TABLE aia_exercise_items ADD COLUMN IF NOT EXISTS back_en TEXT")
            # Migration: add extras JSONB for Flashcards structured fields (word_parts etc.)
            cur.execute("ALTER TABLE aia_exercise_items ADD COLUMN IF NOT EXISTS extras JSONB")
            # Which glossary term is behind the exercise, as text instead of an id.
            cur.execute(
                "ALTER TABLE aia_exercise_items ADD COLUMN IF NOT EXISTS glossary_term TEXT"
            )
            # Backfills the term for flashcards built from the glossary.
            cur.execute("""
                UPDATE aia_exercise_items i SET glossary_term = i.front
                FROM aia_exercise_sets s
                WHERE i.set_id = s.id
                  AND s.mode = 'glossary' AND s.tool = 'flashcards'
                  AND i.glossary_term IS NULL AND i.front <> ''
            """)
            # Empties the quiz pool once because true/false questions were added.
            _reset_quiz_pool_once(cur)
            # The same for grammar, whose instruction line now sits in the exercise text.
            _reset_grammar_pool_once(cur)
            # The trainer hangs on the person now, every level is assessed anew.
            _reset_language_training_once(cur)
            # The round limit is gone, the ring now reads the last answer per card.
            cur.execute("ALTER TABLE aia_exercise_sets DROP COLUMN IF EXISTS last_run_start")
            # The wanted number of exercises, so a retry does not lose it.
            cur.execute("ALTER TABLE aia_exercise_sets ADD COLUMN IF NOT EXISTS requested_count INTEGER")
            # Migration: drop legacy mastery columns if they exist
            for col in ("correct_streak", "total_attempts", "total_correct"):
                cur.execute(f"ALTER TABLE aia_exercise_items DROP COLUMN IF EXISTS {col}")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_schedule_entries (
                    id           SERIAL PRIMARY KEY,
                    -- NULL: the entry belongs to no workspace, only to the user.
                    workspace_id INTEGER
                                   REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id      INTEGER NOT NULL,
                    type         TEXT NOT NULL CHECK (type IN ('deadline', 'termin')),
                    title        TEXT NOT NULL,
                    description  TEXT,
                    due_date     DATE,
                    end_date     DATE,
                    due_time     TIME,
                    is_optional  BOOLEAN NOT NULL DEFAULT FALSE,
                    is_checked   BOOLEAN NOT NULL DEFAULT FALSE,
                    checked_at   TIMESTAMP,
                    origin       TEXT NOT NULL CHECK (origin IN ('llm', 'manual')),
                    source_refs  JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE aia_schedule_entries ADD COLUMN IF NOT EXISTS source_refs JSONB NOT NULL DEFAULT '[]'::jsonb")
            # When set, the appointment runs until this day.
            cur.execute("ALTER TABLE aia_schedule_entries ADD COLUMN IF NOT EXISTS end_date DATE")
            # Existing databases still carry workspace_id as NOT NULL.
            cur.execute("ALTER TABLE aia_schedule_entries ALTER COLUMN workspace_id DROP NOT NULL")
            # How precisely the date appears in the source, day or month only.
            cur.execute("ALTER TABLE aia_schedule_entries ADD COLUMN IF NOT EXISTS date_precision TEXT NOT NULL DEFAULT 'day'")
            # When set, the appointment runs on this day until this time.
            cur.execute("ALTER TABLE aia_schedule_entries ADD COLUMN IF NOT EXISTS end_time TIME")
            # When set, the source names a start and explicitly no end.
            cur.execute("ALTER TABLE aia_schedule_entries ADD COLUMN IF NOT EXISTS is_open_ended BOOLEAN NOT NULL DEFAULT FALSE")
            # When set, the source wrote no year and the system picked the nearest one.
            cur.execute("ALTER TABLE aia_schedule_entries ADD COLUMN IF NOT EXISTS year_assumed BOOLEAN NOT NULL DEFAULT FALSE")
            # Drop legacy columns (were single-position; replaced by source_refs array)
            cur.execute("ALTER TABLE aia_schedule_entries DROP COLUMN IF EXISTS source_ids")
            cur.execute("ALTER TABLE aia_schedule_entries DROP COLUMN IF EXISTS raw_quote")
            cur.execute("ALTER TABLE aia_schedule_entries DROP COLUMN IF EXISTS page_number")
            cur.execute("ALTER TABLE aia_schedule_entries DROP COLUMN IF EXISTS start_time")
            # Its own name per mind map instead of showing the root node from the JSON.
            cur.execute("ALTER TABLE aia_mindmaps ADD COLUMN IF NOT EXISTS title TEXT")
            # The person's own instruction to the tool and whether it missed the material.
            for tabelle in ("aia_mindmaps", "aia_data_tables"):
                cur.execute(f"ALTER TABLE {tabelle} ADD COLUMN IF NOT EXISTS user_instruction TEXT")
                cur.execute(f"ALTER TABLE {tabelle} ADD COLUMN IF NOT EXISTS "
                            "instruction_unmatched BOOLEAN NOT NULL DEFAULT FALSE")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_schedule_workspace_user
                ON aia_schedule_entries(workspace_id, user_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_schedule_due_date
                ON aia_schedule_entries(workspace_id, user_id, due_date)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_schedule_processed_sources (
                    workspace_id  INTEGER NOT NULL
                                    REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id       INTEGER NOT NULL,
                    source_id     INTEGER NOT NULL
                                    REFERENCES aia_sources(id) ON DELETE CASCADE,
                    processed_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (workspace_id, user_id, source_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_schedule_jobs (
                    id            SERIAL PRIMARY KEY,
                    workspace_id  INTEGER NOT NULL
                                    REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id       INTEGER NOT NULL,
                    source_uuids  JSONB NOT NULL DEFAULT '[]'::jsonb,
                    status        TEXT NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'running', 'success', 'failed')),
                    error         TEXT,
                    added_count   INTEGER NOT NULL DEFAULT 0,
                    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_schedule_jobs_workspace_user
                ON aia_schedule_jobs(workspace_id, user_id)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_schedule_source_extractions (
                    source_id        INTEGER PRIMARY KEY
                                       REFERENCES aia_sources(id) ON DELETE CASCADE,
                    candidates       JSONB NOT NULL,
                    classifications  JSONB NOT NULL,
                    extracted_at     TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # Marks that the guided tour already copied its 8 tool examples in for this
            # person, so deleting them never brings them back. Separate from the
            # examples themselves, which is the whole point: they can be gone and this
            # row still stands.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_demo_tools_seeded (
                    workspace_id  INTEGER NOT NULL
                                    REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id       INTEGER NOT NULL,
                    seeded_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (workspace_id, user_id)
                )
            """)

            # Marks that this demo module was handed to this person once, so a module
            # they left stays gone while a newly added one still reaches everybody.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_demo_seeded (
                    workspace_id  INTEGER NOT NULL
                                    REFERENCES aia_workspaces(id) ON DELETE CASCADE,
                    user_id       INTEGER NOT NULL,
                    seeded_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (workspace_id, user_id)
                )
            """)

            # One row per endpoint the admin entered.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS providers (
                    id             SERIAL PRIMARY KEY,
                    name           TEXT NOT NULL UNIQUE,
                    protocol       TEXT NOT NULL,
                    base_url       TEXT NOT NULL,
                    api_key        TEXT,
                    capabilities   JSONB NOT NULL DEFAULT '[]'::jsonb,
                    enabled        BOOLEAN NOT NULL DEFAULT TRUE,
                    last_probed_at TIMESTAMP WITH TIME ZONE,
                    probe_status   TEXT,
                    probe_error    TEXT,
                    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at     TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_providers_protocol
                ON providers(protocol)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_providers_enabled
                ON providers(enabled) WHERE enabled = TRUE
            """)
            # Migration: add voices column (provider-specific voice catalogue)
            cur.execute("""
                ALTER TABLE providers
                ADD COLUMN IF NOT EXISTS voices JSONB NOT NULL DEFAULT '[]'::jsonb
            """)
            # Requests at once per provider and bucket, a missing key means no cap.
            _add_provider_concurrency_once(cur)
            # A person's own interface, NULL is a provider the admin set up for everybody.
            cur.execute("""
                ALTER TABLE providers
                ADD COLUMN IF NOT EXISTS owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_providers_owner
                ON providers(owner_user_id) WHERE owner_user_id IS NOT NULL
            """)

            # One row per feature with the chosen provider and model.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feature_routes (
                    id              SERIAL PRIMARY KEY,
                    feature         TEXT NOT NULL UNIQUE,
                    provider_id     INTEGER REFERENCES providers(id) ON DELETE SET NULL,
                    model_name      TEXT,
                    user_choices    JSONB NOT NULL DEFAULT '[]'::jsonb,
                    provider_models JSONB NOT NULL DEFAULT '{}'::jsonb,
                    provider_sampling JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                ALTER TABLE feature_routes
                ADD COLUMN IF NOT EXISTS provider_models JSONB NOT NULL DEFAULT '{}'::jsonb
            """)
            # Temperature and top_p per provider, empty means send nothing.
            cur.execute("""
                ALTER TABLE feature_routes
                ADD COLUMN IF NOT EXISTS provider_sampling JSONB NOT NULL DEFAULT '{}'::jsonb
            """)
            # Takes over when the first choice fails, its model sits in provider_models.
            cur.execute("""
                ALTER TABLE feature_routes
                ADD COLUMN IF NOT EXISTS fallback_provider_id INTEGER
                    REFERENCES providers(id) ON DELETE SET NULL
            """)
            # The providers of a feature in the admin's order, the first usable one is the standard.
            cur.execute("""
                ALTER TABLE feature_routes
                ADD COLUMN IF NOT EXISTS provider_order JSONB NOT NULL DEFAULT '[]'::jsonb
            """)
            # The screencast_translate route is gone, the screencast reads doc_translate.
            cur.execute("DELETE FROM feature_routes WHERE feature = 'screencast_translate'")

            # The last real call per provider and function, for the availability page.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS provider_checks (
                    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
                    feature     TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    error       TEXT,
                    checked_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (provider_id, feature)
                )
            """)

            # What a model can take, measured once instead of guessed in the admin area.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS model_limits (
                    provider_id   INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
                    model_name    TEXT NOT NULL,
                    window_tokens INTEGER NOT NULL,
                    source        TEXT NOT NULL,
                    thinks        BOOLEAN NOT NULL DEFAULT FALSE,
                    think_off     TEXT NOT NULL DEFAULT '',
                    updated_at    TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (provider_id, model_name)
                )
            """)

            # A silent provider is no longer guessed.
            cur.execute("""
                UPDATE model_limits SET window_tokens = 0, source = 'unbekannt'
                 WHERE source = 'geraten'
            """)

            # One row per request, for daily reports and insight in the admin area.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_llm_usage_log (
                    id          BIGSERIAL PRIMARY KEY,
                    user_id     INTEGER NOT NULL,
                    ts          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    endpoint    VARCHAR(64) NOT NULL,
                    provider    VARCHAR(32),
                    model       VARCHAR(128),
                    tokens_in   INTEGER,
                    tokens_out  INTEGER,
                    duration_ms INTEGER,
                    status      VARCHAR(16) NOT NULL DEFAULT 'ok'
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_usage_log_user_ts
                ON aia_llm_usage_log(user_id, ts DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_usage_log_ts
                ON aia_llm_usage_log(ts DESC)
            """)
            # Permanent record of who has had which pool exercise, so a deleted set
            # cannot free it up again for them.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aia_exercise_pool_seen (
                    pool_item_id INTEGER NOT NULL
                                   REFERENCES aia_exercise_pool(id) ON DELETE CASCADE,
                    user_id      INTEGER NOT NULL,
                    seen_at      TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (pool_item_id, user_id)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_exercise_pool_seen_user
                ON aia_exercise_pool_seen(user_id, seen_at DESC)
            """)
            create_campus_tables(cur)
        conn.commit()

    # tsvector switched to the simple parser so foreign language text gets hits too.
    from loguru import logger as _log
    with get_connection() as conn:
        with conn.cursor() as cur:
            migration_key = "search_vector_simple_migration_done"
            cur.execute("SELECT value FROM settings WHERE key = %s", (migration_key,))
            row = cur.fetchone()
            already_migrated = bool(row and row[0] == "true")

            cur.execute("SELECT COUNT(*) FROM aia_chunks WHERE search_vector IS NULL")
            null_count = cur.fetchone()[0]

            if not already_migrated:
                _log.info("Rewriting search_vector with 'simple' tokenizer for ALL chunks...")
                cur.execute("UPDATE aia_chunks SET search_vector = to_tsvector('simple', content)")
                cur.execute(
                    """INSERT INTO settings (key, value) VALUES (%s, 'true')
                       ON CONFLICT (key) DO UPDATE SET value = 'true'""",
                    (migration_key,),
                )
                _log.info("search_vector simple-migration done.")
            elif null_count > 0:
                _log.info("Backfilling search_vector for {} chunks...", null_count)
                cur.execute("""
                    UPDATE aia_chunks
                    SET search_vector = to_tsvector('simple', content)
                    WHERE search_vector IS NULL
                """)
                _log.info("search_vector backfill done.")
            else:
                _log.info("search_vector: all chunks already populated.")

        conn.commit()

    # hnsw index in its own transaction, on halfvec and only for 2560 dimensions.
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SET LOCAL max_parallel_maintenance_workers = 0")
                cur.execute("SET LOCAL maintenance_work_mem = '256MB'")
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
                    ON aia_chunks USING hnsw ((embedding::halfvec(2560)) halfvec_cosine_ops)
                    WHERE vector_dims(embedding) = 2560
                """)
                conn.commit()
                _log.info("hnsw vector index ready (idx_chunks_embedding_hnsw).")
            except Exception as e:
                conn.rollback()
                _log.warning("hnsw vector index build skipped/failed (vector search falls back to scan): {}", e)
    create_campus_hnsw()


# --- Users ---

