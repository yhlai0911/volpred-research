from __future__ import annotations

from copy import deepcopy
import json
import os
import shutil
import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from volpred.ops.delivery import (
    PublisherArticleDeleteAuthorization,
    plan_publisher_article_delete,
    prepare_publisher_article_delete,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_MIGRATION = (
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724231102_operations_core_article_delete_dependency_contract.sql"
)
RESTORE_MIGRATION = (
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260725015352_operations_core_publisher_delete_restore.sql"
)
RESTORE_NULL_BINDING_FIX = (
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260725020832_fix_publisher_delete_restore_null_binding.sql"
)
DELETE_REQUEST_DEPENDENCIES = tuple(
    REPO_ROOT / "supabase" / "migrations" / name
    for name in (
        "20260723062144_operations_core_work_coordinator.sql",
        "20260724020500_operations_core_effect_outbox.sql",
        "20260724030000_operations_core_effect_outbox_settlement.sql",
        "20260724040000_operations_core_effect_worker_authority.sql",
        "20260724050000_operations_core_effect_receipt_index.sql",
        "20260724060000_operations_core_effect_payload_primary_authority.sql",
        "20260724070000_operations_core_notification_ownership.sql",
        "20260724071000_operations_core_notification_ownership_index.sql",
        "20260724160000_operations_core_primary_authority_rpc.sql",
        "20260725002427_operations_core_publisher_delete_ownership.sql",
        "20260725004020_fix_publisher_delete_approval_record_ambiguity.sql",
        "20260725202655_promote_publisher_delete_scope_approval.sql",
        "20260725205013_remove_owned_request_share_lock.sql",
        "20260726103201_reconcile_stale_owned_publisher_delete.sql",
        "20260726104730_fence_publisher_delete_reconciliation_identity.sql",
        "20260727080000_primary_authority_lifecycle_audit.sql",
    )
)
ARTICLE_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ARTICLE_ID = "22222222-2222-4222-8222-222222222222"
SURVIVOR_ID = "33333333-3333-4333-8333-333333333333"
USER_ID = "44444444-4444-4444-8444-444444444444"
QUESTION_ID = "55555555-5555-4555-8555-555555555555"


def _postgres_bin_dir() -> Path | None:
    homebrew = Path("/opt/homebrew/opt/postgresql@17/bin")
    if (homebrew / "postgres").exists():
        return homebrew
    pg_config = shutil.which("pg_config")
    if pg_config is None:
        return None
    bin_dir = Path(
        subprocess.check_output((pg_config, "--bindir"), text=True).strip()
    )
    return bin_dir if (bin_dir / "postgres").exists() else None


def _create_restore_schema(connection: psycopg.Connection) -> None:
    connection.execute(
        """
        ALTER DATABASE postgres SET timezone TO 'UTC';
        CREATE ROLE service_role NOLOGIN;
        CREATE ROLE anon NOLOGIN;
        CREATE ROLE authenticated NOLOGIN;
        CREATE ROLE volpred_ops_definer NOLOGIN;
        CREATE SCHEMA volpred_ops AUTHORIZATION volpred_ops_definer;

        CREATE TABLE public.profiles (
          id uuid PRIMARY KEY
        );
        CREATE TABLE public.tags (
          id integer PRIMARY KEY,
          name text NOT NULL UNIQUE
        );
        CREATE TABLE public.questions (
          id uuid PRIMARY KEY
        );
        CREATE TABLE public.articles (
          id uuid PRIMARY KEY,
          slug text NOT NULL UNIQUE,
          title text NOT NULL,
          content text,
          excerpt text,
          audience text,
          phase text,
          status text,
          category text,
          proposer text,
          author_id text,
          cover_image_url text,
          details jsonb,
          scheduled_at timestamptz,
          published_at timestamptz,
          created_at timestamptz,
          updated_at timestamptz
        );
        CREATE TABLE public.article_impressions (
          id bigint PRIMARY KEY,
          article_id uuid REFERENCES public.articles(id) ON DELETE CASCADE,
          user_id uuid REFERENCES public.profiles(id),
          session_id text,
          read_time_sec integer,
          impression_date date,
          created_at timestamptz
        );
        CREATE TABLE public.article_reactions (
          article_id uuid REFERENCES public.articles(id) ON DELETE CASCADE,
          user_id uuid REFERENCES public.profiles(id),
          reaction text NOT NULL,
          created_at timestamptz,
          PRIMARY KEY (article_id, user_id, reaction)
        );
        CREATE TABLE public.article_relations (
          source_id uuid REFERENCES public.articles(id) ON DELETE CASCADE,
          target_id uuid REFERENCES public.articles(id) ON DELETE CASCADE,
          relation_type text,
          PRIMARY KEY (source_id, target_id)
        );
        CREATE TABLE public.article_tags (
          article_id uuid REFERENCES public.articles(id) ON DELETE CASCADE,
          tag_id integer REFERENCES public.tags(id),
          PRIMARY KEY (article_id, tag_id)
        );
        CREATE TABLE public.comments (
          id integer PRIMARY KEY,
          article_id uuid REFERENCES public.articles(id) ON DELETE CASCADE,
          user_id uuid REFERENCES public.profiles(id),
          parent_id integer REFERENCES public.comments(id),
          content text NOT NULL,
          status text,
          created_at timestamptz
        );
        CREATE TABLE public.question_articles (
          question_id uuid REFERENCES public.questions(id),
          article_id uuid REFERENCES public.articles(id) ON DELETE CASCADE,
          PRIMARY KEY (question_id, article_id)
        );

        ALTER TABLE public.articles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.article_impressions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.article_reactions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.article_relations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.article_tags ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.comments ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.question_articles ENABLE ROW LEVEL SECURITY;

        GRANT SELECT ON
          public.articles,
          public.article_impressions,
          public.article_reactions,
          public.article_relations,
          public.article_tags,
          public.comments,
          public.question_articles
        TO volpred_ops_definer;
        CREATE POLICY publisher_delete_definer_select
          ON public.articles
          FOR SELECT TO volpred_ops_definer USING (true);
        CREATE POLICY publisher_delete_definer_select
          ON public.article_impressions
          FOR SELECT TO volpred_ops_definer USING (true);
        CREATE POLICY publisher_delete_definer_select
          ON public.article_reactions
          FOR SELECT TO volpred_ops_definer USING (true);
        CREATE POLICY publisher_delete_definer_select
          ON public.article_relations
          FOR SELECT TO volpred_ops_definer USING (true);
        CREATE POLICY publisher_delete_definer_select
          ON public.article_tags
          FOR SELECT TO volpred_ops_definer USING (true);
        CREATE POLICY publisher_delete_definer_select
          ON public.comments
          FOR SELECT TO volpred_ops_definer USING (true);
        CREATE POLICY publisher_delete_definer_select
          ON public.question_articles
          FOR SELECT TO volpred_ops_definer USING (true);
        """
    )
    connection.execute(
        DEPENDENCY_MIGRATION.read_text(encoding="utf-8")
    )
    connection.execute(
        """
        GRANT volpred_ops_definer TO CURRENT_USER;
        GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;
        SET ROLE volpred_ops_definer;
        CREATE OR REPLACE FUNCTION
          volpred_ops.read_publisher_article_delete_candidate(
            p_article_id text
          )
        RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
          article_payload jsonb;
          dependents jsonb;
        BEGIN
          SELECT to_jsonb(article_row)
          INTO article_payload
          FROM public.articles AS article_row
          WHERE article_row.id::text = p_article_id;
          IF article_payload IS NULL THEN
            RETURN NULL;
          END IF;
          dependents := jsonb_build_object(
            'article_impressions', (
              SELECT COALESCE(
                jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
                '[]'::jsonb
              )
              FROM public.article_impressions AS child
              WHERE child.article_id::text = p_article_id
            ),
            'article_reactions', (
              SELECT COALESCE(
                jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
                '[]'::jsonb
              )
              FROM public.article_reactions AS child
              WHERE child.article_id::text = p_article_id
            ),
            'article_relations', (
              SELECT COALESCE(
                jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
                '[]'::jsonb
              )
              FROM public.article_relations AS child
              WHERE child.source_id::text = p_article_id
                 OR child.target_id::text = p_article_id
            ),
            'article_tags', (
              SELECT COALESCE(
                jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
                '[]'::jsonb
              )
              FROM public.article_tags AS child
              WHERE child.article_id::text = p_article_id
            ),
            'comments', (
              SELECT COALESCE(
                jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
                '[]'::jsonb
              )
              FROM public.comments AS child
              WHERE child.article_id::text = p_article_id
            ),
            'question_articles', (
              SELECT COALESCE(
                jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
                '[]'::jsonb
              )
              FROM public.question_articles AS child
              WHERE child.article_id::text = p_article_id
            )
          );
          RETURN jsonb_build_object(
            'article', article_payload,
            'dependents', dependents
          );
        END;
        $$;
        RESET ROLE;
        REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;
        REVOKE volpred_ops_definer FROM CURRENT_USER;
        """
    )
    migration = RESTORE_MIGRATION.read_text(encoding="utf-8")
    connection.execute(migration)
    connection.execute(migration)
    null_binding_fix = RESTORE_NULL_BINDING_FIX.read_text(encoding="utf-8")
    connection.execute(null_binding_fix)
    connection.execute(null_binding_fix)


@pytest.fixture(scope="session")
def restore_postgres_dsn(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[str]:
    bin_dir = _postgres_bin_dir()
    if bin_dir is None:
        if os.environ.get("CI"):
            pytest.fail("PostgreSQL 17 server binaries are required in CI")
        pytest.skip("PostgreSQL server binaries are required")

    root = tmp_path_factory.mktemp("publisher-delete-restore-postgres")
    data_dir = root / "data"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    subprocess.run(
        (
            str(bin_dir / "initdb"),
            "-D",
            str(data_dir),
            "--auth=trust",
            "--no-locale",
            "--encoding=UTF8",
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
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
        check=True,
        capture_output=True,
        text=True,
    )
    dsn = f"postgresql://127.0.0.1:{port}/postgres"
    try:
        with psycopg.connect(dsn, autocommit=True) as connection:
            _create_restore_schema(connection)
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


@pytest.fixture(autouse=True)
def reset_restore_tables(restore_postgres_dsn: str) -> None:
    with psycopg.connect(
        restore_postgres_dsn,
        autocommit=True,
    ) as connection:
        connection.execute(
            """
            TRUNCATE TABLE
              public.article_impressions,
              public.article_reactions,
              public.article_relations,
              public.article_tags,
              public.comments,
              public.question_articles,
              public.articles,
              public.profiles,
              public.tags,
              public.questions
            CASCADE
            """
        )

        connection.execute(
            "INSERT INTO public.profiles (id) VALUES (%s)",
            (USER_ID,),
        )
        connection.execute(
            "INSERT INTO public.tags (id, name) VALUES (7, 'restore-test')"
        )
        connection.execute(
            "INSERT INTO public.questions (id) VALUES (%s)",
            (QUESTION_ID,),
        )
        connection.execute(
            """
            INSERT INTO public.articles (
              id, slug, title, content, excerpt, audience, phase, status,
              category, proposer, author_id, cover_image_url, details,
              scheduled_at, published_at, created_at, updated_at
            )
            VALUES (
              %s, 'mile_restore_survivor', 'Restore survivor', NULL, NULL,
              'research', NULL, 'published', 'milestone', NULL, 'claude',
              NULL, NULL, NULL, %s, %s, %s
            )
            """,
            (
                SURVIVOR_ID,
                "2026-07-25T00:00:00+00:00",
                "2026-07-25T00:00:00+00:00",
                "2026-07-25T00:00:00+00:00",
            ),
        )


@pytest.fixture(scope="session")
def delete_request_postgres_dsn(
    restore_postgres_dsn: str,
) -> str:
    with psycopg.connect(
        restore_postgres_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("ALTER ROLE volpred_ops_definer NOINHERIT")
        for migration in DELETE_REQUEST_DEPENDENCIES:
            connection.execute(migration.read_text(encoding="utf-8"))
    return restore_postgres_dsn


def test_owned_delete_request_promotes_scope_approval_into_work_approval(
    delete_request_postgres_dsn: str,
) -> None:
    candidate = _candidate(article_id=ARTICLE_ID, slug="orphan-owned-delete")
    plan = plan_publisher_article_delete(
        canonical_feed=json.dumps(
            [{"id": f"mile_{index}"} for index in range(500)]
        ).encode(),
        candidates=(candidate,),
        recovery_artifact_ref="private://owned-delete-recovery",
    )
    authorization = PublisherArticleDeleteAuthorization(
        approval_ref="approval:postgres-owned-delete",
        approver_ref="owner:postgres-test",
        approved_at="2026-07-25T20:30:00+00:00",
        scope_sha256=plan.scope_sha256,
    )
    prepared = prepare_publisher_article_delete(
        plan=plan,
        authorization=authorization,
        idempotency_key="postgres-owned-delete",
        work_item_id="publisher-delete-restore-rehearsal:test:delete",
        work_item_version=1,
        payload_ref="private://owned-delete-payload",
        requester_ref="operator:postgres-test",
    )

    with psycopg.connect(
        delete_request_postgres_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        cutover = connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_delete_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "legacy",
                1,
                "operations_core",
                "operator:postgres-test",
                "exercise destructive request admission",
                None,
            ),
        ).fetchone()[0]
        assert (cutover["owner"], cutover["generation"]) == (
            "operations_core",
            2,
        )
        connection.execute(
            """
            SELECT public.volpred_record_publisher_article_delete_approval(
              %s, %s
            )
            """,
            (
                Jsonb(
                    {
                        "approval_ref": authorization.approval_ref,
                        "approver_ref": authorization.approver_ref,
                        "approved_at": authorization.approved_at,
                        "scope_sha256": authorization.scope_sha256,
                    }
                ),
                "operator:postgres-test",
            ),
        ).fetchone()

        request = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_delete(
              %s, %s, %s, %s
            )
            """,
            (
                2,
                prepared.request.idempotency_key,
                prepared.payload.decode(),
                "operator:postgres-test",
            ),
        ).fetchone()[0]
        connection.execute("RESET ROLE")
        work = connection.execute(
            """
            SELECT approval, status, version
            FROM volpred_ops.work_items
            WHERE id = %s
            """,
            (request["work_id"],),
        ).fetchone()
        connection.execute("SET ROLE volpred_ops_definer")
        visible_request = connection.execute(
            """
            SELECT effect_id
            FROM volpred_ops.owned_notification_requests
            WHERE effect_id = %s
            """,
            (request["effect_id"],),
        ).fetchone()
        locked_request = connection.execute(
            """
            SELECT effect_id
            FROM volpred_ops.owned_notification_requests
            WHERE effect_id = %s
            FOR SHARE
            """,
            (request["effect_id"],),
        ).fetchone()
        connection.execute("RESET ROLE")

    assert work == ("approved", "pending", 2)
    assert visible_request == (request["effect_id"],)
    assert locked_request is None


def test_stale_revoked_delete_retry_is_terminalized_without_provider(
    delete_request_postgres_dsn: str,
) -> None:
    candidate = _candidate(
        article_id=SECOND_ARTICLE_ID,
        slug="stale-owned-delete-retry",
    )
    plan = plan_publisher_article_delete(
        canonical_feed=json.dumps(
            [{"id": f"mile_stale_{index}"} for index in range(500)]
        ).encode(),
        candidates=(candidate,),
        recovery_artifact_ref="private://stale-owned-delete-recovery",
    )
    authorization = PublisherArticleDeleteAuthorization(
        approval_ref="approval:postgres-stale-owned-delete",
        approver_ref="owner:postgres-test",
        approved_at="2026-07-26T10:00:00+00:00",
        scope_sha256=plan.scope_sha256,
    )
    prepared = prepare_publisher_article_delete(
        plan=plan,
        authorization=authorization,
        idempotency_key="postgres-stale-owned-delete",
        work_item_id="publisher-delete-reconciliation:test:stale",
        work_item_version=1,
        payload_ref="private://stale-owned-delete-payload",
        requester_ref="operator:postgres-test",
    )
    worker_id = "effect-worker:publisher-article-delete"
    primary_token = "primary-stale-owned-delete-token"

    with psycopg.connect(
        delete_request_postgres_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        owner = connection.execute(
            "SELECT public.volpred_read_publisher_article_delete_owner()"
        ).fetchone()[0]
        if owner["owner"] == "legacy":
            owner = connection.execute(
                """
                SELECT public.volpred_transfer_publisher_article_delete_owner(
                  %s, %s, 'operations_core', %s, %s, NULL
                )
                """,
                (
                    "legacy",
                    owner["generation"],
                    "operator:postgres-test",
                    "prepare stale retry reconciliation",
                ),
            ).fetchone()[0]
        connection.execute(
            """
            SELECT public.volpred_record_publisher_article_delete_approval(
              %s, %s
            )
            """,
            (
                Jsonb(
                    {
                        "approval_ref": authorization.approval_ref,
                        "approver_ref": authorization.approver_ref,
                        "approved_at": authorization.approved_at,
                        "scope_sha256": authorization.scope_sha256,
                    }
                ),
                "operator:postgres-test",
            ),
        )
        request = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_delete(
              %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                prepared.request.idempotency_key,
                prepared.payload.decode(),
                "operator:postgres-test",
            ),
        ).fetchone()[0]
        decoy_request = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_delete(
              %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                "postgres-stale-owned-delete-decoy",
                prepared.payload.decode(),
                "operator:postgres-test",
            ),
        ).fetchone()[0]
        primary = connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              'operations-core-primary', %s, 300, %s
            )
            """,
            (worker_id, primary_token),
        ).fetchone()[0]
        attempt = connection.execute(
            """
            SELECT public.volpred_begin_owned_publisher_article_delete(
              %s, %s, %s, 300, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                request["effect_id"],
                worker_id,
                "work-stale-delete-attempt-1",
                "outbox-stale-delete-attempt-1",
                primary_token,
            ),
        ).fetchone()[0]
        retry = connection.execute(
            """
            SELECT public.volpred_settle_owned_publisher_article_delete(
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                attempt["work_id"],
                attempt["work_version"],
                "work-stale-delete-attempt-1",
                attempt["effect"]["id"],
                attempt["outbox_sequence"],
                attempt["attempt_count"],
                attempt["worker_id"],
                "outbox-stale-delete-attempt-1",
                attempt["primary_authority_key"],
                attempt["primary_authority_holder_ref"],
                attempt["primary_authority_epoch"],
                primary_token,
                attempt["authority_request_sha256"],
                attempt["outbox_claim_ref"],
                attempt["primary_authority_ref"],
                "retryable_failure",
                None,
                None,
                "publisher_article_delete_provider_error",
                "test:stale-delete:retryable-provider-error",
                "a" * 64,
            ),
        ).fetchone()[0]
        assert retry["disposition"] == "retry_scheduled"
        connection.execute(
            """
            SELECT public.volpred_revoke_publisher_article_delete_approval(
              %s, %s, %s
            )
            """,
            (
                authorization.approval_ref,
                "operator:postgres-test",
                "revoke destructive rehearsal approval",
            ),
        )
        connection.execute(
            """
            SELECT public.volpred_release_primary_authority(
              'operations-core-primary', %s, %s, %s
            )
            """,
            (worker_id, primary["epoch"], primary_token),
        )
        rolled_back = connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_delete_owner(
              'operations_core', %s, 'legacy', %s, %s, %s
            )
            """,
            (
                owner["generation"],
                "operator:postgres-test",
                "exact rollback after destructive rehearsal",
                owner["generation"],
            ),
        ).fetchone()[0]

        connection.execute("RESET ROLE")
        connection.execute(
            """
            DELETE FROM volpred_ops.owned_notification_requests
            WHERE effect_id = %s
            """,
            (decoy_request["effect_id"],),
        )
        connection.execute(
            """
            UPDATE volpred_ops.owned_notification_requests
            SET work_id = %s
            WHERE effect_id = %s
            """,
            (decoy_request["work_id"], request["effect_id"]),
        )
        connection.execute("SET ROLE service_role")
        cross_linked = connection.execute(
            """
            SELECT public.volpred_reconcile_stale_owned_publisher_article_delete(
              25, %s
            )
            """,
            ("effect-worker:publisher-delete-reconciliation",),
        ).fetchone()[0]
        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_ops.owned_notification_requests
            SET work_id = %s
            WHERE effect_id = %s
            """,
            (request["work_id"], request["effect_id"]),
        )
        connection.execute("SET ROLE service_role")
        reconciliation = connection.execute(
            """
            SELECT public.volpred_reconcile_stale_owned_publisher_article_delete(
              25, %s
            )
            """,
            ("effect-worker:publisher-delete-reconciliation",),
        ).fetchone()[0]
        replay = connection.execute(
            """
            SELECT public.volpred_reconcile_stale_owned_publisher_article_delete(
              25, %s
            )
            """,
            ("effect-worker:publisher-delete-reconciliation",),
        ).fetchone()[0]
        connection.execute("RESET ROLE")
        durable = connection.execute(
            """
            SELECT
              (SELECT status FROM volpred_ops.work_items WHERE id = %s),
              (SELECT status FROM volpred_ops.effect_requests WHERE id = %s),
              (SELECT status FROM volpred_ops.effect_outbox
               WHERE effect_id = %s),
              (SELECT status FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s AND attempt_count = 1),
              (SELECT disposition
               FROM volpred_ops.effect_attempt_receipts
               WHERE effect_id = %s AND attempt_count = 1),
              (SELECT count(*)
               FROM volpred_ops.owned_publisher_delete_reconciliation_receipts
               WHERE effect_id = %s),
              (SELECT count(*) FROM volpred_ops.work_receipts
               WHERE work_id = %s AND outcome = 'failed')
            """,
            (
                request["work_id"],
                request["effect_id"],
                request["effect_id"],
                request["effect_id"],
                request["effect_id"],
                request["effect_id"],
                request["work_id"],
            ),
        ).fetchone()

    assert rolled_back["owner"] == "legacy"
    assert cross_linked["reconciled_count"] == 0
    assert reconciliation["reconciled_count"] == 1
    assert reconciliation["receipts"][0]["effect_id"] == request["effect_id"]
    assert replay["reconciled_count"] == 0
    assert durable == (
        "failed",
        "dead_lettered",
        "dead_lettered",
        "retry_scheduled",
        "retry_scheduled",
        1,
        1,
    )


def _article(article_id: str, slug: str) -> dict:
    timestamp = "2026-07-25T00:00:00+00:00"
    return {
        "id": article_id,
        "slug": slug,
        "title": f"Restore {slug}",
        "content": "Exact recovery bytes.",
        "excerpt": None,
        "audience": "research",
        "phase": "operations-core",
        "status": "published",
        "category": "milestone",
        "proposer": "codex",
        "author_id": "claude",
        "cover_image_url": None,
        "details": {"restore": True},
        "scheduled_at": None,
        "published_at": timestamp,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _candidate(
    article_id: str = ARTICLE_ID,
    slug: str = "mile_restore_exact",
) -> dict:
    timestamp = "2026-07-25T00:00:00+00:00"
    return {
        "article": _article(article_id, slug),
        "dependents": {
            "article_impressions": [
                {
                    "id": 101,
                    "article_id": article_id,
                    "user_id": USER_ID,
                    "session_id": "restore-session",
                    "read_time_sec": 42,
                    "impression_date": "2026-07-25",
                    "created_at": timestamp,
                }
            ],
            "article_reactions": [
                {
                    "article_id": article_id,
                    "user_id": USER_ID,
                    "reaction": "bookmark",
                    "created_at": timestamp,
                }
            ],
            "article_relations": [
                {
                    "source_id": article_id,
                    "target_id": SURVIVOR_ID,
                    "relation_type": "related",
                }
            ],
            "article_tags": [
                {"article_id": article_id, "tag_id": 7}
            ],
            "comments": [
                {
                    "id": 201,
                    "article_id": article_id,
                    "user_id": USER_ID,
                    "parent_id": None,
                    "content": "Restore comment.",
                    "status": "visible",
                    "created_at": timestamp,
                }
            ],
            "question_articles": [
                {
                    "question_id": QUESTION_ID,
                    "article_id": article_id,
                }
            ],
        },
    }


def _restore(
    connection: psycopg.Connection,
    candidates: list[dict],
) -> dict:
    connection.execute("SET ROLE service_role")
    try:
        return connection.execute(
            """
            SELECT public.volpred_restore_publisher_article_delete_batch(%s)
            """,
            (Jsonb(candidates),),
        ).fetchone()[0]
    finally:
        connection.execute("RESET ROLE")


def _read_candidate(
    connection: psycopg.Connection,
    article_id: str,
) -> dict | None:
    return connection.execute(
        """
        SELECT volpred_ops.read_publisher_article_delete_candidate(%s)
        """,
        (article_id,),
    ).fetchone()[0]


def test_restore_rpc_restores_six_tables_and_exact_replay_is_read_only(
    restore_postgres_dsn: str,
) -> None:
    candidate = _candidate()
    with psycopg.connect(
        restore_postgres_dsn,
        autocommit=True,
    ) as connection:
        normalized_article = connection.execute(
            """
            SELECT to_jsonb(parsed)
            FROM jsonb_populate_record(NULL::public.articles, %s) AS parsed
            """,
            (Jsonb(candidate["article"]),),
        ).fetchone()[0]
        assert normalized_article == candidate["article"]
        first = _restore(connection, [candidate])
        assert first == {
            "schema_version": "publisher-article-delete-restore-batch.v1",
            "candidate_count": 1,
            "restored_count": 1,
            "restored": True,
        }
        assert _read_candidate(connection, ARTICLE_ID) == candidate
        before = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM public.articles),
              (SELECT count(*) FROM public.article_impressions),
              (SELECT count(*) FROM public.article_reactions),
              (SELECT count(*) FROM public.article_relations),
              (SELECT count(*) FROM public.article_tags),
              (SELECT count(*) FROM public.comments),
              (SELECT count(*) FROM public.question_articles)
            """
        ).fetchone()
        replay = _restore(connection, [candidate])
        after = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM public.articles),
              (SELECT count(*) FROM public.article_impressions),
              (SELECT count(*) FROM public.article_reactions),
              (SELECT count(*) FROM public.article_relations),
              (SELECT count(*) FROM public.article_tags),
              (SELECT count(*) FROM public.comments),
              (SELECT count(*) FROM public.question_articles)
            """
        ).fetchone()

    assert replay["restored_count"] == 0
    assert after == before


def test_restore_rpc_deduplicates_one_relation_present_on_both_fk_edges(
    restore_postgres_dsn: str,
) -> None:
    first = _candidate()
    second = _candidate(SECOND_ARTICLE_ID, "mile_restore_second")
    relation = {
        "source_id": ARTICLE_ID,
        "target_id": SECOND_ARTICLE_ID,
        "relation_type": "related",
    }
    first["dependents"]["article_relations"] = [relation]
    second["dependents"]["article_relations"] = [relation]
    second["dependents"]["article_impressions"][0]["id"] = 102
    second["dependents"]["comments"][0]["id"] = 202
    with psycopg.connect(
        restore_postgres_dsn,
        autocommit=True,
    ) as connection:
        receipt = _restore(connection, [first, second])
        relation_count = connection.execute(
            """
            SELECT count(*)
            FROM public.article_relations
            WHERE source_id = %s AND target_id = %s
            """,
            (ARTICLE_ID, SECOND_ARTICLE_ID),
        ).fetchone()[0]
        assert _read_candidate(connection, ARTICLE_ID) == first
        assert _read_candidate(connection, SECOND_ARTICLE_ID) == second

    assert receipt["restored_count"] == 2
    assert relation_count == 1


def test_restore_rpc_scope_drift_preflight_writes_nothing(
    restore_postgres_dsn: str,
) -> None:
    drifted = _candidate()
    second = _candidate(SECOND_ARTICLE_ID, "mile_restore_second")
    with psycopg.connect(
        restore_postgres_dsn,
        autocommit=True,
    ) as connection:
        article = deepcopy(drifted["article"])
        article["title"] = "Concurrent remote edit"
        columns = tuple(article)
        connection.execute(
            f"""
            INSERT INTO public.articles ({", ".join(columns)})
            VALUES ({", ".join(["%s"] * len(columns))})
            """,
            tuple(Jsonb(value) if isinstance(value, dict) else value for value in article.values()),
        )
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="scope drifted",
        ):
            _restore(connection, [drifted, second])
        second_count = connection.execute(
            "SELECT count(*) FROM public.articles WHERE id = %s",
            (SECOND_ARTICLE_ID,),
        ).fetchone()[0]
        observed_title = connection.execute(
            "SELECT title FROM public.articles WHERE id = %s",
            (ARTICLE_ID,),
        ).fetchone()[0]

    assert second_count == 0
    assert observed_title == "Concurrent remote edit"


def test_restore_rpc_mid_batch_failure_rolls_back_every_insert(
    restore_postgres_dsn: str,
) -> None:
    candidate = _candidate()
    with psycopg.connect(
        restore_postgres_dsn,
        autocommit=True,
    ) as connection:
        connection.execute(
            """
            CREATE OR REPLACE FUNCTION public.reject_restore_tag()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'injected restore failure';
            END;
            $$;
            CREATE TRIGGER reject_restore_tag
            BEFORE INSERT ON public.article_tags
            FOR EACH ROW EXECUTE FUNCTION public.reject_restore_tag();
            """
        )
        try:
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="injected restore failure",
            ):
                _restore(connection, [candidate])
        finally:
            connection.execute(
                """
                DROP TRIGGER IF EXISTS reject_restore_tag
                  ON public.article_tags;
                DROP FUNCTION IF EXISTS public.reject_restore_tag();
                """
            )
        counts = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM public.articles WHERE id = %s),
              (SELECT count(*) FROM public.article_impressions
               WHERE article_id = %s),
              (SELECT count(*) FROM public.article_reactions
               WHERE article_id = %s),
              (SELECT count(*) FROM public.article_relations
               WHERE source_id = %s OR target_id = %s),
              (SELECT count(*) FROM public.article_tags
               WHERE article_id = %s)
            """,
            (
                ARTICLE_ID,
                ARTICLE_ID,
                ARTICLE_ID,
                ARTICLE_ID,
                ARTICLE_ID,
                ARTICLE_ID,
            ),
        ).fetchone()

    assert counts == (0, 0, 0, 0, 0)


def test_restore_rpc_rejects_nullable_child_detached_from_candidate(
    restore_postgres_dsn: str,
) -> None:
    candidate = _candidate()
    candidate["dependents"]["article_impressions"][0]["article_id"] = None
    with psycopg.connect(
        restore_postgres_dsn,
        autocommit=True,
    ) as connection:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="article_impressions rows drifted",
        ):
            _restore(connection, [candidate])
        article_count = connection.execute(
            "SELECT count(*) FROM public.articles WHERE id = %s",
            (ARTICLE_ID,),
        ).fetchone()[0]

    assert article_count == 0


def test_restore_rpc_acl_and_definer_shape_are_fail_closed(
    restore_postgres_dsn: str,
) -> None:
    with psycopg.connect(restore_postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT
              procedure.proowner = (
                SELECT oid FROM pg_roles
                WHERE rolname = 'volpred_ops_definer'
              ),
              procedure.prosecdef,
              procedure.proconfig = ARRAY['search_path=""'],
              has_function_privilege(
                'service_role', procedure.oid, 'EXECUTE'
              ),
              has_function_privilege('anon', procedure.oid, 'EXECUTE'),
              has_function_privilege(
                'authenticated', procedure.oid, 'EXECUTE'
              ),
              has_function_privilege('public', procedure.oid, 'EXECUTE'),
              has_table_privilege(
                'service_role', 'public.articles', 'INSERT'
              ),
              has_table_privilege(
                'service_role', 'public.article_tags', 'INSERT'
              ),
              has_schema_privilege(
                'volpred_ops_definer', 'public', 'CREATE'
              )
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'public'
              AND procedure.proname =
                'volpred_restore_publisher_article_delete_batch'
            """
        ).fetchone()

    assert row == (
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
    )
