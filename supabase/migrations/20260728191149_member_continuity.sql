-- Server-owned member continuity boundary for Issue #23.
--
-- Anonymous choices stay in the browser until authentication.  The backend
-- validates each choice independently, applies it exactly once, and returns a
-- durable receipt.  Browser/Data API roles receive no direct access to the
-- private schema or RPC.

CREATE SCHEMA IF NOT EXISTS volpred_member;
REVOKE ALL ON SCHEMA volpred_member FROM PUBLIC;

DO $create_member_worker$
BEGIN
  CREATE ROLE volpred_member_worker
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$create_member_worker$;

DO $validate_member_worker$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_roles
    WHERE rolname = 'volpred_member_worker'
      AND NOT rolcanlogin
      AND NOT rolsuper
      AND NOT rolcreatedb
      AND NOT rolcreaterole
      AND NOT rolreplication
      AND NOT rolbypassrls
      AND NOT rolinherit
  ) THEN
    RAISE EXCEPTION
      'existing volpred_member_worker role has unsafe attributes';
  END IF;
END;
$validate_member_worker$;

GRANT volpred_member_worker TO CURRENT_USER;
GRANT CREATE ON SCHEMA public TO volpred_member_worker;

DO $reacquire_member_functions$
BEGIN
  IF pg_catalog.to_regprocedure(
    'public.apply_volpred_member_intent('
    'uuid,text,text,jsonb,bytea,bytea)'
  ) IS NOT NULL THEN
    EXECUTE pg_catalog.format(
      'ALTER FUNCTION public.apply_volpred_member_intent('
      'uuid,text,text,jsonb,bytea,bytea) OWNER TO %I',
      CURRENT_USER
    );
  END IF;
  IF pg_catalog.to_regprocedure(
    'public.read_volpred_member_continuity(uuid)'
  ) IS NOT NULL THEN
    EXECUTE pg_catalog.format(
      'ALTER FUNCTION public.read_volpred_member_continuity(uuid) '
      'OWNER TO %I',
      CURRENT_USER
    );
  END IF;
  IF pg_catalog.to_regprocedure(
    'public.delete_volpred_member_continuity(uuid,text,bytea)'
  ) IS NOT NULL THEN
    EXECUTE pg_catalog.format(
      'ALTER FUNCTION public.delete_volpred_member_continuity('
      'uuid,text,bytea) OWNER TO %I',
      CURRENT_USER
    );
  END IF;
END;
$reacquire_member_functions$;

CREATE TABLE IF NOT EXISTS volpred_member.follows (
  user_id uuid NOT NULL
    REFERENCES public.profiles(id) ON DELETE CASCADE,
  target_kind text NOT NULL
    CHECK (target_kind IN ('article', 'topic')),
  target_id text NOT NULL
    CHECK (
      target_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    ),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (user_id, target_kind, target_id)
);

CREATE TABLE IF NOT EXISTS volpred_member.reminders (
  user_id uuid NOT NULL
    REFERENCES public.profiles(id) ON DELETE CASCADE,
  intent_id text NOT NULL
    CHECK (
      intent_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$'
    ),
  article_id uuid NOT NULL
    REFERENCES public.articles(id) ON DELETE CASCADE,
  remind_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'scheduled'
    CHECK (status IN ('scheduled', 'delivered', 'cancelled')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (user_id, intent_id)
);

CREATE INDEX IF NOT EXISTS member_reminders_due_idx
  ON volpred_member.reminders (remind_at, user_id)
  WHERE status = 'scheduled';

CREATE TABLE IF NOT EXISTS volpred_member.intent_receipts (
  user_id uuid NOT NULL
    REFERENCES public.profiles(id) ON DELETE CASCADE,
  intent_id text NOT NULL
    CHECK (
      intent_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$'
    ),
  kind text NOT NULL
    CHECK (kind IN ('save', 'follow', 'reminder')),
  request_digest bytea NOT NULL
    CHECK (octet_length(request_digest) = 32),
  result jsonb NOT NULL
    CHECK (jsonb_typeof(result) = 'object'),
  applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (user_id, intent_id)
);

CREATE TABLE IF NOT EXISTS volpred_member.privacy_tombstones (
  subject_digest bytea PRIMARY KEY
    CHECK (octet_length(subject_digest) = 32),
  deleted_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS volpred_member.privacy_action_receipts (
  idempotency_key text PRIMARY KEY
    CHECK (
      idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$'
    ),
  subject_digest bytea NOT NULL
    CHECK (octet_length(subject_digest) = 32),
  result jsonb NOT NULL
    CHECK (jsonb_typeof(result) = 'object'),
  acted_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

ALTER TABLE volpred_member.follows ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_member.follows FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_member.reminders ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_member.reminders FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_member.intent_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_member.intent_receipts FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_member.privacy_tombstones ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_member.privacy_tombstones FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_member.privacy_action_receipts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_member.privacy_action_receipts
  FORCE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA volpred_member FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA volpred_member FROM PUBLIC;

GRANT USAGE ON SCHEMA public, volpred_member
  TO volpred_member_worker;
GRANT SELECT ON public.profiles, public.articles
  TO volpred_member_worker;
GRANT SELECT, INSERT, DELETE ON public.article_reactions
  TO volpred_member_worker;
GRANT SELECT, DELETE ON public.questions
  TO volpred_member_worker;
GRANT SELECT, INSERT, DELETE
  ON volpred_member.follows,
     volpred_member.reminders,
     volpred_member.intent_receipts,
     volpred_member.privacy_action_receipts
  TO volpred_member_worker;
GRANT SELECT, INSERT ON volpred_member.privacy_tombstones
  TO volpred_member_worker;
GRANT UPDATE (deleted_at) ON volpred_member.privacy_tombstones
  TO volpred_member_worker;

DROP POLICY IF EXISTS member_worker_select ON public.profiles;
CREATE POLICY member_worker_select ON public.profiles
  FOR SELECT TO volpred_member_worker USING (true);
DROP POLICY IF EXISTS member_worker_select ON public.articles;
CREATE POLICY member_worker_select ON public.articles
  FOR SELECT TO volpred_member_worker USING (true);
DROP POLICY IF EXISTS member_worker_select ON public.article_reactions;
CREATE POLICY member_worker_select ON public.article_reactions
  FOR SELECT TO volpred_member_worker USING (true);
DROP POLICY IF EXISTS member_worker_insert ON public.article_reactions;
CREATE POLICY member_worker_insert ON public.article_reactions
  FOR INSERT TO volpred_member_worker WITH CHECK (true);
DROP POLICY IF EXISTS member_worker_delete ON public.article_reactions;
CREATE POLICY member_worker_delete ON public.article_reactions
  FOR DELETE TO volpred_member_worker USING (true);
DROP POLICY IF EXISTS member_worker_select ON public.questions;
CREATE POLICY member_worker_select ON public.questions
  FOR SELECT TO volpred_member_worker USING (true);
DROP POLICY IF EXISTS member_worker_delete ON public.questions;
CREATE POLICY member_worker_delete ON public.questions
  FOR DELETE TO volpred_member_worker USING (true);

DO $member_worker_policies$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'follows',
    'reminders',
    'intent_receipts',
    'privacy_tombstones',
    'privacy_action_receipts'
  ]
  LOOP
    EXECUTE pg_catalog.format(
      'DROP POLICY IF EXISTS member_worker_select ON volpred_member.%I',
      table_name
    );
    EXECUTE pg_catalog.format(
      'CREATE POLICY member_worker_select ON volpred_member.%I '
      'FOR SELECT TO volpred_member_worker USING (true)',
      table_name
    );
  END LOOP;
  FOREACH table_name IN ARRAY ARRAY[
    'follows',
    'reminders',
    'intent_receipts',
    'privacy_tombstones',
    'privacy_action_receipts'
  ]
  LOOP
    EXECUTE pg_catalog.format(
      'DROP POLICY IF EXISTS member_worker_insert ON volpred_member.%I',
      table_name
    );
    EXECUTE pg_catalog.format(
      'CREATE POLICY member_worker_insert ON volpred_member.%I '
      'FOR INSERT TO volpred_member_worker WITH CHECK (true)',
      table_name
    );
  END LOOP;
  EXECUTE
    'DROP POLICY IF EXISTS member_worker_update '
    'ON volpred_member.privacy_tombstones';
  EXECUTE
    'CREATE POLICY member_worker_update '
    'ON volpred_member.privacy_tombstones '
    'FOR UPDATE TO volpred_member_worker '
    'USING (true) WITH CHECK (true)';
  FOREACH table_name IN ARRAY ARRAY[
    'follows',
    'reminders',
    'intent_receipts',
    'privacy_action_receipts'
  ]
  LOOP
    EXECUTE pg_catalog.format(
      'DROP POLICY IF EXISTS member_worker_delete ON volpred_member.%I',
      table_name
    );
    EXECUTE pg_catalog.format(
      'CREATE POLICY member_worker_delete ON volpred_member.%I '
      'FOR DELETE TO volpred_member_worker USING (true)',
      table_name
    );
  END LOOP;
END;
$member_worker_policies$;

DO $revoke_data_api_roles$
DECLARE
  role_name text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
  LOOP
    IF EXISTS (
      SELECT 1
      FROM pg_catalog.pg_roles
      WHERE rolname = role_name
    ) THEN
      EXECUTE pg_catalog.format(
        'REVOKE ALL ON SCHEMA volpred_member FROM %I',
        role_name
      );
      EXECUTE pg_catalog.format(
        'REVOKE ALL ON ALL TABLES IN SCHEMA volpred_member FROM %I',
        role_name
      );
      EXECUTE pg_catalog.format(
        'REVOKE ALL ON ALL SEQUENCES IN SCHEMA volpred_member FROM %I',
        role_name
      );
    END IF;
  END LOOP;
END;
$revoke_data_api_roles$;

CREATE OR REPLACE FUNCTION public.apply_volpred_member_intent(
  p_user_id uuid,
  p_intent_id text,
  p_kind text,
  p_payload jsonb,
  p_request_digest bytea,
  p_subject_digest bytea
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $apply_intent$
DECLARE
  existing_digest bytea;
  existing_result jsonb;
  resolved_article_id uuid;
  target_kind text;
  target_id text;
  remind_at timestamptz;
  result jsonb;
BEGIN
  IF p_user_id IS NULL THEN
    RAISE EXCEPTION 'member user_id is required';
  END IF;
  IF p_intent_id IS NULL
     OR p_intent_id
        !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$' THEN
    RAISE EXCEPTION 'member intent_id is invalid';
  END IF;
  IF p_kind IS NULL
     OR p_kind NOT IN ('save', 'follow', 'reminder') THEN
    RAISE EXCEPTION 'member intent kind is invalid';
  END IF;
  IF p_payload IS NULL
     OR pg_catalog.jsonb_typeof(p_payload) <> 'object' THEN
    RAISE EXCEPTION 'member intent payload must be an object';
  END IF;
  IF p_request_digest IS NULL
     OR p_subject_digest IS NULL
     OR pg_catalog.octet_length(p_request_digest) <> 32
     OR pg_catalog.octet_length(p_subject_digest) <> 32 THEN
    RAISE EXCEPTION 'member intent digest is invalid';
  END IF;

  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-member:subject:' || p_user_id::text,
      0
    )
  );
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-member:intent:'
      || p_user_id::text
      || ':'
      || p_intent_id,
      0
    )
  );

  IF EXISTS (
    SELECT 1
    FROM volpred_member.privacy_tombstones AS tombstone
    WHERE tombstone.subject_digest = p_subject_digest
  ) THEN
    RAISE EXCEPTION 'member continuity subject was deleted';
  END IF;

  SELECT receipt.request_digest, receipt.result
  INTO existing_digest, existing_result
  FROM volpred_member.intent_receipts AS receipt
  WHERE receipt.user_id = p_user_id
    AND receipt.intent_id = p_intent_id;
  IF FOUND THEN
    IF existing_digest <> p_request_digest THEN
      RAISE EXCEPTION 'member intent_id was reused';
    END IF;
    RETURN existing_result
      || pg_catalog.jsonb_build_object('duplicate', true);
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM public.profiles AS profile
    WHERE profile.id = p_user_id
      AND profile.status = 'active'
  ) THEN
    RAISE EXCEPTION 'active member profile is required';
  END IF;

  IF p_kind = 'save' THEN
    IF (
         SELECT pg_catalog.count(*)
         FROM pg_catalog.jsonb_object_keys(p_payload)
       ) <> 1
       OR NOT p_payload ? 'article_id'
       OR pg_catalog.jsonb_typeof(p_payload -> 'article_id') <> 'string'
       OR (p_payload ->> 'article_id')
          !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-'
              '[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN
      RAISE EXCEPTION 'member save payload is invalid';
    END IF;
    resolved_article_id := (p_payload ->> 'article_id')::uuid;
    IF NOT EXISTS (
      SELECT 1
      FROM public.articles AS article
      WHERE article.id = resolved_article_id
        AND article.status = 'published'
    ) THEN
      RAISE EXCEPTION 'published member article is required';
    END IF;
    INSERT INTO public.article_reactions (
      article_id,
      user_id,
      reaction
    )
    VALUES (resolved_article_id, p_user_id, 'bookmark')
    ON CONFLICT DO NOTHING;

  ELSIF p_kind = 'follow' THEN
    IF (
         SELECT pg_catalog.count(*)
         FROM pg_catalog.jsonb_object_keys(p_payload)
       ) <> 2
       OR NOT p_payload ?& ARRAY['target_kind', 'target_id']
       OR pg_catalog.jsonb_typeof(p_payload -> 'target_kind') <> 'string'
       OR pg_catalog.jsonb_typeof(p_payload -> 'target_id') <> 'string' THEN
      RAISE EXCEPTION 'member follow payload is invalid';
    END IF;
    target_kind := p_payload ->> 'target_kind';
    target_id := p_payload ->> 'target_id';
    IF target_kind NOT IN ('article', 'topic') THEN
      RAISE EXCEPTION 'member follow target_kind is invalid';
    END IF;
    IF target_kind = 'article' THEN
      IF target_id
         !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-'
              '[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
         OR NOT EXISTS (
           SELECT 1
           FROM public.articles AS article
           WHERE article.id = target_id::uuid
             AND article.status = 'published'
         ) THEN
        RAISE EXCEPTION 'published member article is required';
      END IF;
    ELSIF target_id
          !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN
      RAISE EXCEPTION 'member follow target_id is invalid';
    END IF;
    INSERT INTO volpred_member.follows (
      user_id,
      target_kind,
      target_id
    )
    VALUES (p_user_id, target_kind, target_id)
    ON CONFLICT DO NOTHING;

  ELSE
    IF (
         SELECT pg_catalog.count(*)
         FROM pg_catalog.jsonb_object_keys(p_payload)
       ) <> 2
       OR NOT p_payload ?& ARRAY['article_id', 'remind_at']
       OR pg_catalog.jsonb_typeof(p_payload -> 'article_id') <> 'string'
       OR pg_catalog.jsonb_typeof(p_payload -> 'remind_at') <> 'string'
       OR (p_payload ->> 'article_id')
          !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-'
              '[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN
      RAISE EXCEPTION 'member reminder payload is invalid';
    END IF;
    resolved_article_id := (p_payload ->> 'article_id')::uuid;
    BEGIN
      remind_at := (p_payload ->> 'remind_at')::timestamptz;
    EXCEPTION
      WHEN invalid_datetime_format OR datetime_field_overflow THEN
        RAISE EXCEPTION 'member reminder remind_at is invalid';
    END;
    IF remind_at <= pg_catalog.clock_timestamp()
       OR remind_at
          > pg_catalog.clock_timestamp() + interval '366 days' THEN
      RAISE EXCEPTION 'member reminder remind_at is invalid';
    END IF;
    IF NOT EXISTS (
      SELECT 1
      FROM public.articles AS article
      WHERE article.id = resolved_article_id
        AND article.status = 'published'
    ) THEN
      RAISE EXCEPTION 'published member article is required';
    END IF;
    INSERT INTO volpred_member.reminders (
      user_id,
      intent_id,
      article_id,
      remind_at
    )
    VALUES (
      p_user_id,
      p_intent_id,
      resolved_article_id,
      remind_at
    );
  END IF;

  result := pg_catalog.jsonb_build_object(
    'contract', 'member-intent-receipt.v1',
    'intent_id', p_intent_id,
    'kind', p_kind,
    'status', 'applied',
    'duplicate', false
  );
  INSERT INTO volpred_member.intent_receipts (
    user_id,
    intent_id,
    kind,
    request_digest,
    result
  )
  VALUES (
    p_user_id,
    p_intent_id,
    p_kind,
    p_request_digest,
    result
  );
  RETURN result;
END;
$apply_intent$;

CREATE OR REPLACE FUNCTION public.read_volpred_member_continuity(
  p_user_id uuid
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $read_member$
DECLARE
  saved_article_ids jsonb;
  follows jsonb;
  reminders jsonb;
  question_count bigint;
BEGIN
  IF p_user_id IS NULL OR NOT EXISTS (
    SELECT 1
    FROM public.profiles AS profile
    WHERE profile.id = p_user_id
      AND profile.status = 'active'
  ) THEN
    RAISE EXCEPTION 'active member profile is required';
  END IF;

  SELECT COALESCE(
    pg_catalog.jsonb_agg(
      reaction.article_id
      ORDER BY reaction.article_id
    ),
    '[]'::jsonb
  )
  INTO saved_article_ids
  FROM public.article_reactions AS reaction
  WHERE reaction.user_id = p_user_id
    AND reaction.reaction = 'bookmark';

  SELECT COALESCE(
    pg_catalog.jsonb_agg(
      pg_catalog.jsonb_build_object(
        'target_kind', follow.target_kind,
        'target_id', follow.target_id
      )
      ORDER BY follow.target_kind, follow.target_id
    ),
    '[]'::jsonb
  )
  INTO follows
  FROM volpred_member.follows AS follow
  WHERE follow.user_id = p_user_id;

  SELECT COALESCE(
    pg_catalog.jsonb_agg(
      pg_catalog.jsonb_build_object(
        'intent_id', reminder.intent_id,
        'article_id', reminder.article_id,
        'remind_at', pg_catalog.to_char(
          pg_catalog.timezone('UTC', reminder.remind_at),
          'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ),
        'status', reminder.status
      )
      ORDER BY reminder.remind_at, reminder.intent_id
    ),
    '[]'::jsonb
  )
  INTO reminders
  FROM volpred_member.reminders AS reminder
  WHERE reminder.user_id = p_user_id;

  SELECT pg_catalog.count(*)
  INTO question_count
  FROM public.questions AS question
  WHERE question.user_id = p_user_id;

  RETURN pg_catalog.jsonb_build_object(
    'contract', 'member-continuity-state.v1',
    'user_id', p_user_id,
    'saved_article_ids', saved_article_ids,
    'follows', follows,
    'reminders', reminders,
    'question_count', question_count
  );
END;
$read_member$;

CREATE OR REPLACE FUNCTION public.delete_volpred_member_continuity(
  p_user_id uuid,
  p_idempotency_key text,
  p_subject_digest bytea
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $delete_member$
DECLARE
  existing_subject_digest bytea;
  existing_result jsonb;
  removed_article_reactions bigint;
  removed_follows bigint;
  removed_reminders bigint;
  removed_questions bigint;
  removed_intent_receipts bigint;
  result jsonb;
BEGIN
  IF p_user_id IS NULL THEN
    RAISE EXCEPTION 'member user_id is required';
  END IF;
  IF p_idempotency_key IS NULL
     OR p_idempotency_key
        !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$' THEN
    RAISE EXCEPTION 'member privacy idempotency_key is invalid';
  END IF;
  IF p_subject_digest IS NULL
     OR pg_catalog.octet_length(p_subject_digest) <> 32 THEN
    RAISE EXCEPTION 'member privacy subject digest is invalid';
  END IF;

  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-member:subject:' || p_user_id::text,
      0
    )
  );
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-member:privacy:' || p_idempotency_key,
      0
    )
  );

  SELECT receipt.subject_digest, receipt.result
  INTO existing_subject_digest, existing_result
  FROM volpred_member.privacy_action_receipts AS receipt
  WHERE receipt.idempotency_key = p_idempotency_key;
  IF FOUND THEN
    IF existing_subject_digest <> p_subject_digest THEN
      RAISE EXCEPTION 'member privacy idempotency_key was reused';
    END IF;
    RETURN existing_result
      || pg_catalog.jsonb_build_object('duplicate', true);
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM public.profiles AS profile
    WHERE profile.id = p_user_id
  ) THEN
    RAISE EXCEPTION 'member profile is required';
  END IF;

  DELETE FROM public.article_reactions AS reaction
  WHERE reaction.user_id = p_user_id;
  GET DIAGNOSTICS
    removed_article_reactions = ROW_COUNT;

  DELETE FROM volpred_member.follows AS follow
  WHERE follow.user_id = p_user_id;
  GET DIAGNOSTICS removed_follows = ROW_COUNT;

  DELETE FROM volpred_member.reminders AS reminder
  WHERE reminder.user_id = p_user_id;
  GET DIAGNOSTICS removed_reminders = ROW_COUNT;

  DELETE FROM public.questions AS question
  WHERE question.user_id = p_user_id;
  GET DIAGNOSTICS removed_questions = ROW_COUNT;

  DELETE FROM volpred_member.intent_receipts AS receipt
  WHERE receipt.user_id = p_user_id;
  GET DIAGNOSTICS removed_intent_receipts = ROW_COUNT;

  INSERT INTO volpred_member.privacy_tombstones (
    subject_digest,
    deleted_at
  )
  VALUES (p_subject_digest, pg_catalog.clock_timestamp())
  ON CONFLICT (subject_digest) DO UPDATE SET
    deleted_at = EXCLUDED.deleted_at;

  result := pg_catalog.jsonb_build_object(
    'contract', 'member-continuity-delete-receipt.v1',
    'idempotency_key', p_idempotency_key,
    'status', 'deleted',
    'duplicate', false,
    'removed', pg_catalog.jsonb_build_object(
      'article_reactions', removed_article_reactions,
      'follows', removed_follows,
      'reminders', removed_reminders,
      'questions', removed_questions,
      'intent_receipts', removed_intent_receipts
    )
  );
  INSERT INTO volpred_member.privacy_action_receipts (
    idempotency_key,
    subject_digest,
    result
  )
  VALUES (
    p_idempotency_key,
    p_subject_digest,
    result
  );
  RETURN result;
END;
$delete_member$;

REVOKE ALL ON FUNCTION public.apply_volpred_member_intent(
  uuid, text, text, jsonb, bytea, bytea
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.read_volpred_member_continuity(uuid)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION public.delete_volpred_member_continuity(
  uuid, text, bytea
) FROM PUBLIC;

DO $grant_service_role$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_roles
    WHERE rolname = 'service_role'
  ) THEN
    RAISE EXCEPTION 'service_role is required for member continuity';
  END IF;
  REVOKE ALL ON FUNCTION public.apply_volpred_member_intent(
    uuid, text, text, jsonb, bytea, bytea
  ) FROM anon, authenticated;
  REVOKE ALL ON FUNCTION public.read_volpred_member_continuity(uuid)
    FROM anon, authenticated;
  REVOKE ALL ON FUNCTION public.delete_volpred_member_continuity(
    uuid, text, bytea
  ) FROM anon, authenticated;
  GRANT EXECUTE ON FUNCTION public.apply_volpred_member_intent(
    uuid, text, text, jsonb, bytea, bytea
  ) TO service_role;
  GRANT EXECUTE ON FUNCTION public.read_volpred_member_continuity(uuid)
    TO service_role;
  GRANT EXECUTE ON FUNCTION public.delete_volpred_member_continuity(
    uuid, text, bytea
  ) TO service_role;
END;
$grant_service_role$;

ALTER FUNCTION public.apply_volpred_member_intent(
  uuid, text, text, jsonb, bytea, bytea
) OWNER TO volpred_member_worker;
ALTER FUNCTION public.read_volpred_member_continuity(uuid)
  OWNER TO volpred_member_worker;
ALTER FUNCTION public.delete_volpred_member_continuity(
  uuid, text, bytea
) OWNER TO volpred_member_worker;

REVOKE CREATE ON SCHEMA public FROM volpred_member_worker;
REVOKE volpred_member_worker FROM CURRENT_USER;
