from __future__ import annotations

import hashlib
import hmac
import json
import re
import shutil
import socket
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = tuple(
    (REPO_ROOT / "supabase" / "migrations").glob(
        "*_member_continuity.sql"
    )
)
ANALYTICS_MIGRATIONS = tuple(
    REPO_ROOT / "supabase" / "migrations" / name
    for name in (
        "20260726154115_analytics_privacy_tracer.sql",
        "20260727094656_analytics_ingress_rpc.sql",
        "20260728190500_analytics_member_identity_rpc.sql",
    )
)
USER_ID = "f19ec496-1f49-4185-a0ee-07a3d8cd5e52"
ARTICLE_ID = "9f39fda0-f663-45a8-97db-52a3b3ea8136"
QUESTION_ID = "b3250314-e22d-4e0e-b30a-4b0b9530b8fd"
ANONYMOUS_ID = "anon-member-continuity-1"
ANALYTICS_SECRET = b"member-continuity-analytics-secret-32b"
ANALYTICS_DIGEST_KEY_ID = "member-continuity-test-key-v1"


def test_active_frontend_source_is_pinned_and_checked_out_for_ci() -> None:
    targets = json.loads(
        (REPO_ROOT / "config" / "project_targets.json").read_text(
            encoding="utf-8"
        )
    )
    active = targets["frontends"][targets["active_frontend"]]
    assert active["source_repository"] == "yhlai0911/volpred-v2"
    revision = active["source_revision"]
    assert re.fullmatch(r"[0-9a-f]{40}", revision)

    workflow = (
        REPO_ROOT / ".github" / "workflows" / "pytest.yml"
    ).read_text(encoding="utf-8")
    assert "VOLPRED_V2_CI_DEPLOY_KEY" in workflow
    assert "steps.frontend-target.outputs.revision" in workflow
    assert (
        "repository: ${{ steps.frontend-target.outputs.repository }}"
        in workflow
    )
    assert "path: frontend-v2-fix" in workflow

    frontend = REPO_ROOT / active["path"]
    assert (
        frontend / "tests" / "member-continuity-postgres-e2e.mjs"
    ).is_file(), "CI must checkout the pinned active frontend before pytest"
    assert subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
        cwd=frontend,
        check=True,
        capture_output=True,
        text=True,
    ).returncode == 0
    # Local development may be ahead of the CI pin, but the exact files this
    # E2E executes must still match the audited revision. Unrelated drafts,
    # PDFs, or package metadata cannot turn into false pinned evidence.
    execution_surface = (
        "src/lib/browser-anonymous-identity.ts",
        "src/lib/member-continuity-browser.ts",
        "src/lib/member-continuity-http.ts",
        "src/lib/member-continuity-service.ts",
        "src/lib/member-continuity.ts",
        "src/lib/member-question-http.ts",
        "tests/member-continuity-postgres-e2e.mjs",
        "tests/register-hook.mjs",
        "tests/ts-resolve-hook.mjs",
    )
    subprocess.run(
        ["git", "diff", "--quiet", revision, "--", *execution_surface],
        cwd=frontend,
        check=True,
    )


def test_managed_postgres_owner_transfer_is_bounded() -> None:
    migrations = (
        *ANALYTICS_MIGRATIONS[-1:],
        *MIGRATIONS,
    )

    for migration in migrations:
        source = migration.read_text(encoding="utf-8")
        assert "CURRENT_USER = 'postgres'" in source
        assert "WITH INHERIT FALSE" in source
        assert "WITH SET TRUE" in source
        assert "GRANTED BY CURRENT_USER" in source
        assert "SET LOCAL ROLE" in source
        assert "RESET ROLE" in source
        assert "$reacquire_" not in source


def _postgres_bin_dir() -> Path | None:
    homebrew = Path("/opt/homebrew/opt/postgresql@17/bin")
    if (homebrew / "postgres").exists():
        return homebrew
    pg_config = shutil.which("pg_config")
    if pg_config is None:
        return None
    bindir = Path(
        subprocess.check_output(
            (pg_config, "--bindir"),
            text=True,
        ).strip()
    )
    return bindir if (bindir / "postgres").exists() else None


@pytest.fixture(scope="module")
def member_postgres_dsn(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[str]:
    assert len(MIGRATIONS) == 1, "member continuity migration is required"
    bin_dir = _postgres_bin_dir()
    if bin_dir is None:
        if __import__("os").environ.get("CI"):
            pytest.fail("PostgreSQL server binaries are required in CI")
        pytest.skip("PostgreSQL server binaries are required")
    root = tmp_path_factory.mktemp("member-continuity-postgres")
    data_dir = root / "data"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    completed = subprocess.run(
        (
            str(bin_dir / "initdb"),
            "--auth=trust",
            "--encoding=UTF8",
            "--no-locale",
            "-D",
            str(data_dir),
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    completed = subprocess.run(
        (
            str(bin_dir / "pg_ctl"),
            "-D",
            str(data_dir),
            "-l",
            str(root / "postgres.log"),
            "-o",
            f"-F -h 127.0.0.1 -p {port} -k /tmp",
            "-w",
            "start",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    dsn = f"postgresql://127.0.0.1:{port}/postgres"
    try:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(
                "CREATE ROLE member_migration_runner "
                "NOLOGIN CREATEROLE BYPASSRLS"
            )
            connection.execute(
                "GRANT CREATE ON DATABASE postgres "
                "TO member_migration_runner"
            )
            connection.execute(
                "GRANT USAGE, CREATE ON SCHEMA public "
                "TO member_migration_runner WITH GRANT OPTION"
            )
            connection.execute("CREATE ROLE anon NOLOGIN")
            connection.execute("CREATE ROLE authenticated NOLOGIN")
            connection.execute("CREATE ROLE service_role NOLOGIN")
            connection.execute(
                """
                CREATE TABLE public.profiles (
                  id uuid PRIMARY KEY,
                  status text NOT NULL DEFAULT 'active'
                );
                CREATE TABLE public.articles (
                  id uuid PRIMARY KEY,
                  status text NOT NULL
                );
                CREATE TABLE public.article_reactions (
                  article_id uuid NOT NULL REFERENCES public.articles(id),
                  user_id uuid NOT NULL REFERENCES public.profiles(id),
                  reaction text NOT NULL,
                  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                  PRIMARY KEY (article_id, user_id, reaction)
                );
                CREATE TABLE public.questions (
                  id uuid PRIMARY KEY,
                  user_id uuid REFERENCES public.profiles(id),
                  source text NOT NULL DEFAULT 'user',
                  question text NOT NULL DEFAULT 'test question',
                  status text NOT NULL DEFAULT 'evaluating',
                  proposer text NOT NULL DEFAULT '會員'
                );
                ALTER TABLE public.profiles
                  OWNER TO member_migration_runner;
                ALTER TABLE public.articles
                  OWNER TO member_migration_runner;
                ALTER TABLE public.article_reactions
                  OWNER TO member_migration_runner;
                ALTER TABLE public.questions
                  OWNER TO member_migration_runner;
                """
            )
            connection.execute(
                """
                GRANT SELECT, REFERENCES
                  ON public.profiles, public.articles
                  TO member_migration_runner;
                GRANT SELECT, INSERT, DELETE
                  ON public.article_reactions
                  TO member_migration_runner;
                GRANT SELECT, DELETE
                  ON public.questions
                  TO member_migration_runner;
                """
            )
            connection.execute(
                "INSERT INTO public.profiles(id) VALUES (%s)",
                (USER_ID,),
            )
            connection.execute(
                "INSERT INTO public.articles(id,status) "
                "VALUES (%s,'published')",
                (ARTICLE_ID,),
            )
            connection.execute("SET ROLE member_migration_runner")
            for _ in range(2):
                for migration in ANALYTICS_MIGRATIONS:
                    connection.execute(
                        migration.read_text(encoding="utf-8")
                    )
            connection.execute(MIGRATIONS[0].read_text(encoding="utf-8"))
            connection.execute(MIGRATIONS[0].read_text(encoding="utf-8"))
            connection.execute("RESET ROLE")
        yield dsn
    finally:
        subprocess.run(
            (
                str(bin_dir / "pg_ctl"),
                "-D",
                str(data_dir),
                "-m",
                "fast",
                "-w",
                "stop",
            ),
            check=True,
            capture_output=True,
            text=True,
        )


def _digest(value: object) -> bytes:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).digest()


@pytest.fixture(autouse=True)
def reset_member_continuity_state(
    member_postgres_dsn: str,
) -> None:
    with psycopg.connect(
        member_postgres_dsn,
        autocommit=True,
    ) as connection:
        connection.execute(
            """
            TRUNCATE TABLE
              volpred_member.privacy_action_receipts,
              volpred_member.privacy_tombstones,
              volpred_member.intent_receipts,
              volpred_member.reminders,
              volpred_member.follows,
              volpred_analytics.privacy_action_receipts,
              volpred_analytics.privacy_tombstones,
              volpred_analytics.event_dedupe_tombstones,
              volpred_analytics.identity_merge_receipts,
              volpred_analytics.privacy_preferences,
              volpred_analytics.identity_links,
              volpred_analytics.events,
              volpred_analytics.digest_key_identity,
              public.article_reactions,
              public.questions
            RESTART IDENTITY
            """
        )


def _apply(
    connection: psycopg.Connection,
    *,
    intent_id: str,
    kind: str,
    payload: dict[str, str],
) -> dict:
    subject_digest = hashlib.sha256(
        f"member:{USER_ID}".encode()
    ).digest()
    return connection.execute(
        """
        SELECT public.apply_volpred_member_intent(
          %s, %s, %s, %s, %s, %s
        )
        """,
        (
            USER_ID,
            intent_id,
            kind,
            Jsonb(payload),
            _digest({"kind": kind, "payload": payload}),
            subject_digest,
        ),
    ).fetchone()[0]


def _read(connection: psycopg.Connection) -> dict:
    return connection.execute(
        """
        SELECT public.read_volpred_member_continuity(%s)
        """,
        (USER_ID,),
    ).fetchone()[0]


def _delete(
    connection: psycopg.Connection,
    *,
    idempotency_key: str = "member-delete-1",
) -> dict:
    return connection.execute(
        """
        SELECT public.delete_volpred_member_continuity(%s, %s, %s)
        """,
        (
            USER_ID,
            idempotency_key,
            hashlib.sha256(f"member:{USER_ID}".encode()).digest(),
        ),
    ).fetchone()[0]


def _analytics_subject_digest(subject_kind: str, subject_id: str) -> bytes:
    return hmac.new(
        ANALYTICS_SECRET,
        f"subject:{subject_kind}:{subject_id}".encode(),
        hashlib.sha256,
    ).digest()


def _record_anonymous_event(
    connection: psycopg.Connection,
    *,
    idempotency_key: str,
) -> dict:
    return connection.execute(
        """
        SELECT public.record_volpred_analytics_event(
          %s, 'content_impression', pg_catalog.clock_timestamp(),
          %s, NULL, %s, %s, %s, %s, %s, %s, NULL
        )
        """,
        (
            idempotency_key,
            ANONYMOUS_ID,
            Jsonb({"content_id": ARTICLE_ID, "surface": "article"}),
            hashlib.sha256(f"payload:{idempotency_key}".encode()).digest(),
            hashlib.sha256(f"key:{idempotency_key}".encode()).digest(),
            ANALYTICS_DIGEST_KEY_ID,
            hmac.new(
                ANALYTICS_SECRET,
                (
                    "digest-key-verifier:"
                    f"{ANALYTICS_DIGEST_KEY_ID}"
                ).encode(),
                hashlib.sha256,
            ).digest(),
            _analytics_subject_digest("anonymous", ANONYMOUS_ID),
        ),
    ).fetchone()[0]


def test_service_role_applies_each_choice_once_and_replay_is_exact(
    member_postgres_dsn: str,
) -> None:
    remind_at = datetime.now(UTC) + timedelta(days=30)
    intents = (
        (
            "save-1",
            "save",
            {"article_id": ARTICLE_ID},
        ),
        (
            "follow-1",
            "follow",
            {
                "target_kind": "article",
                "target_id": ARTICLE_ID,
            },
        ),
        (
            "reminder-1",
            "reminder",
            {
                "article_id": ARTICLE_ID,
                "remind_at": remind_at.isoformat(),
            },
        ),
    )
    with psycopg.connect(member_postgres_dsn) as connection:
        connection.execute("SET ROLE service_role")
        first = [
            _apply(
                connection,
                intent_id=intent_id,
                kind=kind,
                payload=payload,
            )
            for intent_id, kind, payload in intents
        ]
        replay = _apply(
            connection,
            intent_id="save-1",
            kind="save",
            payload={"article_id": ARTICLE_ID},
        )
        connection.execute("RESET ROLE")
        counts = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM public.article_reactions),
              (SELECT count(*) FROM volpred_member.follows),
              (SELECT count(*) FROM volpred_member.reminders),
              (SELECT count(*) FROM volpred_member.intent_receipts)
            """
        ).fetchone()

    assert [item["duplicate"] for item in first] == [False, False, False]
    assert replay["duplicate"] is True
    assert counts == (1, 1, 1, 3)


def test_private_member_and_analytics_rpcs_are_service_role_only(
    member_postgres_dsn: str,
) -> None:
    functions = (
        (
            "public.apply_volpred_member_intent("
            "uuid,text,text,jsonb,bytea,bytea)"
        ),
        "public.read_volpred_member_continuity(uuid)",
        (
            "public.delete_volpred_member_continuity("
            "uuid,text,bytea)"
        ),
        (
            "public.merge_volpred_analytics_identity("
            "text,text,text,timestamp with time zone,bytea,bytea)"
        ),
        (
            "public.delete_volpred_analytics_identity("
            "text,text,timestamp with time zone,bytea)"
        ),
    )
    with psycopg.connect(member_postgres_dsn) as connection:
        privileges = {
            role: tuple(
                connection.execute(
                    "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                    (role, function_name),
                ).fetchone()[0]
                for function_name in functions
            )
            for role in (
                "public",
                "anon",
                "authenticated",
                "service_role",
            )
        }
        private_tables = connection.execute(
            """
            SELECT
              namespace.nspname,
              relation.relname,
              relation.relrowsecurity,
              relation.relforcerowsecurity,
              has_table_privilege(
                'service_role',
                relation.oid,
                'SELECT,INSERT,UPDATE,DELETE'
              )
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname IN (
              'volpred_member',
              'volpred_analytics'
            )
              AND relation.relkind = 'r'
            ORDER BY namespace.nspname, relation.relname
            """
        ).fetchall()
        function_hardening = connection.execute(
            """
            SELECT
              procedure.proname,
              procedure.prosecdef,
              procedure.proconfig,
              owner.rolname,
              owner.rolcanlogin,
              owner.rolsuper,
              owner.rolcreatedb,
              owner.rolcreaterole,
              owner.rolreplication,
              owner.rolbypassrls,
              owner.rolinherit
            FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            JOIN pg_catalog.pg_roles AS owner
              ON owner.oid = procedure.proowner
            WHERE namespace.nspname = 'public'
              AND procedure.proname IN (
                'apply_volpred_member_intent',
                'read_volpred_member_continuity',
                'delete_volpred_member_continuity',
                'merge_volpred_analytics_identity',
                'delete_volpred_analytics_identity'
              )
            ORDER BY procedure.proname
            """
        ).fetchall()

    assert privileges["public"] == (False,) * len(functions)
    assert privileges["anon"] == (False,) * len(functions)
    assert privileges["authenticated"] == (False,) * len(functions)
    assert privileges["service_role"] == (True,) * len(functions)
    assert private_tables
    assert all(
        rls and force_rls and not direct_access
        for _, _, rls, force_rls, direct_access in private_tables
    )
    assert len(function_hardening) == len(functions)
    assert all(
        security_definer
            and config is not None
            and any(
                item in {
                    'search_path=""',
                    "search_path=pg_catalog, volpred_analytics",
                }
                for item in config
            )
        for (
            _,
            security_definer,
            config,
            owner,
            can_login,
            superuser,
            create_db,
            create_role,
            replication,
            bypass_rls,
            inherit,
        ) in function_hardening
        if owner in {
            "volpred_member_worker",
            "volpred_analytics_worker",
        }
    )
    assert {
        (name, owner)
        for name, _, _, owner, *_ in function_hardening
    } == {
        ("apply_volpred_member_intent", "volpred_member_worker"),
        ("read_volpred_member_continuity", "volpred_member_worker"),
        ("delete_volpred_member_continuity", "volpred_member_worker"),
        (
            "merge_volpred_analytics_identity",
            "volpred_analytics_worker",
        ),
        (
            "delete_volpred_analytics_identity",
            "volpred_analytics_worker",
        ),
    }
    assert all(
        not any(
            (
                can_login,
                superuser,
                create_db,
                create_role,
                replication,
                bypass_rls,
                inherit,
            )
        )
        for _, _, _, _, can_login, superuser, create_db, create_role,
        replication, bypass_rls, inherit in function_hardening
    )


def test_privileged_rpcs_reject_null_digest_evidence(
    member_postgres_dsn: str,
) -> None:
    calls = (
        (
            """
            SELECT public.apply_volpred_member_intent(
              %s, 'null-digest-save', 'save', %s, NULL, %s
            )
            """,
            (
                USER_ID,
                Jsonb({"article_id": ARTICLE_ID}),
                hashlib.sha256(f"member:{USER_ID}".encode()).digest(),
            ),
            "member intent digest is invalid",
        ),
        (
            """
            SELECT public.apply_volpred_member_intent(
              %s, 'null-subject-save', 'save', %s, %s, NULL
            )
            """,
            (
                USER_ID,
                Jsonb({"article_id": ARTICLE_ID}),
                _digest(
                    {
                        "kind": "save",
                        "payload": {"article_id": ARTICLE_ID},
                    }
                ),
            ),
            "member intent digest is invalid",
        ),
        (
            """
            SELECT public.delete_volpred_member_continuity(
              %s, 'null-member-delete', NULL
            )
            """,
            (USER_ID,),
            "member privacy subject digest is invalid",
        ),
        (
            """
            SELECT public.merge_volpred_analytics_identity(
              'null-anonymous-merge', %s, %s,
              pg_catalog.clock_timestamp(), NULL, %s
            )
            """,
            (
                ANONYMOUS_ID,
                USER_ID,
                _analytics_subject_digest("user", USER_ID),
            ),
            "analytics identity evidence is invalid",
        ),
        (
            """
            SELECT public.delete_volpred_analytics_identity(
              %s, 'null-analytics-delete',
              pg_catalog.clock_timestamp(), NULL
            )
            """,
            (USER_ID,),
            "analytics privacy evidence is invalid",
        ),
    )
    with psycopg.connect(
        member_postgres_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        for sql, params, message in calls:
            with pytest.raises(
                psycopg.errors.RaiseException,
                match=message,
            ):
                connection.execute(sql, params)


def test_service_role_reads_only_the_explainable_member_state(
    member_postgres_dsn: str,
) -> None:
    remind_at = datetime.now(UTC) + timedelta(days=30)
    intents = (
        (
            "save-read-1",
            "save",
            {"article_id": ARTICLE_ID},
        ),
        (
            "follow-read-1",
            "follow",
            {
                "target_kind": "article",
                "target_id": ARTICLE_ID,
            },
        ),
        (
            "reminder-read-1",
            "reminder",
            {
                "article_id": ARTICLE_ID,
                "remind_at": remind_at.isoformat(),
            },
        ),
    )
    with psycopg.connect(member_postgres_dsn) as connection:
        connection.execute("SET ROLE service_role")
        for intent_id, kind, payload in intents:
            _apply(
                connection,
                intent_id=intent_id,
                kind=kind,
                payload=payload,
            )
        state = _read(connection)

    assert state == {
        "contract": "member-continuity-state.v1",
        "user_id": USER_ID,
        "saved_article_ids": [ARTICLE_ID],
        "follows": [
            {
                "target_kind": "article",
                "target_id": ARTICLE_ID,
            }
        ],
        "reminders": [
                {
                    "intent_id": "reminder-read-1",
                    "article_id": ARTICLE_ID,
                    "remind_at": remind_at.isoformat().replace(
                        "+00:00",
                        "Z",
                    ),
                    "status": "scheduled",
                }
        ],
        "question_count": 0,
    }


def test_privacy_delete_is_exact_replayable_and_prevents_recollection(
    member_postgres_dsn: str,
) -> None:
    remind_at = datetime.now(UTC) + timedelta(days=30)
    intents = (
        (
            "save-delete-1",
            "save",
            {"article_id": ARTICLE_ID},
        ),
        (
            "follow-delete-1",
            "follow",
            {
                "target_kind": "article",
                "target_id": ARTICLE_ID,
            },
        ),
        (
            "reminder-delete-1",
            "reminder",
            {
                "article_id": ARTICLE_ID,
                "remind_at": remind_at.isoformat(),
            },
        ),
    )
    with psycopg.connect(member_postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO public.questions(id,user_id) VALUES (%s,%s)",
            (QUESTION_ID, USER_ID),
        )
        connection.execute("SET ROLE service_role")
        for intent_id, kind, payload in intents:
            _apply(
                connection,
                intent_id=intent_id,
                kind=kind,
                payload=payload,
            )

        first = _delete(connection)
        state_after_delete = _read(connection)
        replay = _delete(connection)
    with psycopg.connect(
        member_postgres_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="subject was deleted",
        ):
            _apply(
                connection,
                intent_id="save-after-delete",
                kind="save",
                payload={"article_id": ARTICLE_ID},
            )

    expected_counts = {
        "article_reactions": 1,
        "follows": 1,
        "reminders": 1,
        "questions": 1,
        "intent_receipts": 3,
    }
    assert first == {
        "contract": "member-continuity-delete-receipt.v1",
        "idempotency_key": "member-delete-1",
        "status": "deleted",
        "duplicate": False,
        "removed": expected_counts,
    }
    assert replay == {
        **first,
        "duplicate": True,
    }
    assert state_after_delete == {
        "contract": "member-continuity-state.v1",
        "user_id": USER_ID,
        "saved_article_ids": [],
        "follows": [],
        "reminders": [],
        "question_count": 0,
    }


def test_analytics_identity_merge_and_delete_cover_the_anonymous_history(
    member_postgres_dsn: str,
) -> None:
    user_digest = _analytics_subject_digest("user", USER_ID)
    anonymous_digest = _analytics_subject_digest(
        "anonymous",
        ANONYMOUS_ID,
    )
    with psycopg.connect(member_postgres_dsn) as connection:
        connection.execute("SET ROLE service_role")
        recorded = _record_anonymous_event(
            connection,
            idempotency_key="member-continuity-event-before-login",
        )
        merged = connection.execute(
            """
            SELECT public.merge_volpred_analytics_identity(
              %s, %s, %s, pg_catalog.clock_timestamp(), %s, %s
            )
            """,
            (
                "member-continuity-identity-merge-1",
                ANONYMOUS_ID,
                USER_ID,
                anonymous_digest,
                user_digest,
            ),
        ).fetchone()[0]
        merge_replay = connection.execute(
            """
            SELECT public.merge_volpred_analytics_identity(
              %s, %s, %s, pg_catalog.clock_timestamp(), %s, %s
            )
            """,
            (
                "member-continuity-identity-merge-1",
                ANONYMOUS_ID,
                USER_ID,
                anonymous_digest,
                user_digest,
            ),
        ).fetchone()[0]
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="idempotency_key was reused",
        ), connection.transaction():
            connection.execute(
                """
                    SELECT public.merge_volpred_analytics_identity(
                      %s, %s, %s, pg_catalog.clock_timestamp(), %s, %s
                    )
                    """,
                (
                    "member-continuity-identity-merge-1",
                    "another-anonymous-identity",
                    USER_ID,
                    anonymous_digest,
                    user_digest,
                ),
            )
        deleted = connection.execute(
            """
            SELECT public.delete_volpred_analytics_identity(
              %s, %s, pg_catalog.clock_timestamp(), %s
            )
            """,
            (
                USER_ID,
                "member-continuity-analytics-delete-1",
                user_digest,
            ),
        ).fetchone()[0]
        delete_replay = connection.execute(
            """
            SELECT public.delete_volpred_analytics_identity(
              %s, %s, pg_catalog.clock_timestamp(), %s
            )
            """,
            (
                USER_ID,
                "member-continuity-analytics-delete-1",
                user_digest,
            ),
        ).fetchone()[0]
        rejected = _record_anonymous_event(
            connection,
            idempotency_key="member-continuity-event-after-delete",
        )
        connection.execute("RESET ROLE")
        state = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM volpred_analytics.events),
              (SELECT count(*) FROM volpred_analytics.identity_links),
              (SELECT count(*) FROM volpred_analytics.privacy_tombstones)
            """
        ).fetchone()

    assert recorded["accepted"] is True
    assert merged == {
        "contract": "analytics-identity-merge-receipt.v1",
        "idempotency_key": "member-continuity-identity-merge-1",
        "anonymous_id": ANONYMOUS_ID,
        "user_id": USER_ID,
        "merged_events": 1,
        "duplicate": False,
    }
    assert merge_replay == {**merged, "duplicate": True}
    assert deleted == {
        "contract": "analytics-privacy-delete-receipt.v1",
        "idempotency_key": "member-continuity-analytics-delete-1",
        "status": "deleted",
        "duplicate": False,
        "removed_raw_events": 1,
        "removed_identity_links": 1,
    }
    assert delete_replay == {**deleted, "duplicate": True}
    assert rejected["accepted"] is False
    assert rejected["reason"] == "deleted"
    assert state == (0, 0, 2)


def test_browser_http_service_and_postgres_complete_all_four_member_flows(
    member_postgres_dsn: str,
) -> None:
    bin_dir = _postgres_bin_dir()
    assert bin_dir is not None
    node_raw = (
        __import__("os").environ.get("VOLPRED_TEST_NODE")
        or shutil.which("node")
    )
    if node_raw is None:
        pytest.fail("Node.js 20+ runtime is required")
    node = Path(node_raw)
    version = subprocess.run(
        (str(node), "--version"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        node_major = int(version.removeprefix("v").split(".", 1)[0])
    except ValueError:
        pytest.fail(f"unable to parse Node.js version: {version}")
    if node_major < 20:
        pytest.fail(f"Node.js 20+ is required, got {version}")
    harness = (
        REPO_ROOT
        / "frontend-v2-fix"
        / "tests"
        / "member-continuity-postgres-e2e.mjs"
    )
    environment = {
        **__import__("os").environ,
        "VOLPRED_TEST_POSTGRES_DSN": member_postgres_dsn,
        "VOLPRED_TEST_PSQL": str(bin_dir / "psql"),
    }
    completed = subprocess.run(
        (
            str(node),
            "--experimental-strip-types",
            "--import",
            str(
                REPO_ROOT
                / "frontend-v2-fix"
                / "tests"
                / "register-hook.mjs"
            ),
            str(harness),
        ),
        cwd=REPO_ROOT / "frontend-v2-fix",
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
