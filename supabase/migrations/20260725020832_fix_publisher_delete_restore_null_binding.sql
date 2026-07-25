-- Fail closed when a nullable child row is explicitly detached from recovery.
--
-- SQL ``NULL <> expected`` evaluates to UNKNOWN, not TRUE.  The initial
-- atomic restore function therefore needed a forward-only guard before its
-- typed row validation for nullable article_impressions.article_id and
-- comments.article_id (and for defense in depth across all six child tables).
-- Preserve the deployed function as an uncallable internal v1 and expose a
-- service-role-only wrapper whose JSON identity checks use IS DISTINCT FROM.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
SET ROLE volpred_ops_definer;

DO $$
BEGIN
  IF pg_catalog.to_regprocedure(
      'public.volpred_restore_publisher_article_delete_batch_v1(jsonb)'
    ) IS NULL THEN
    IF pg_catalog.to_regprocedure(
        'public.volpred_restore_publisher_article_delete_batch(jsonb)'
      ) IS NULL THEN
      RAISE EXCEPTION
        'publisher delete restore v1 function is required';
    END IF;
    ALTER FUNCTION
      public.volpred_restore_publisher_article_delete_batch(jsonb)
      RENAME TO volpred_restore_publisher_article_delete_batch_v1;
  END IF;
END;
$$;

REVOKE ALL ON FUNCTION
  public.volpred_restore_publisher_article_delete_batch_v1(jsonb)
FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION
  public.volpred_restore_publisher_article_delete_batch(
    p_expected_candidates jsonb
  )
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  candidate jsonb;
  dependents_payload jsonb;
  target_article_id text;
BEGIN
  IF jsonb_typeof(p_expected_candidates) <> 'array' THEN
    RAISE EXCEPTION
      'publisher delete restore candidates must be an array';
  END IF;
  FOR candidate IN
    SELECT item
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
  LOOP
    target_article_id := candidate -> 'article' ->> 'id';
    dependents_payload := candidate -> 'dependents';

    IF EXISTS (
      SELECT 1
      FROM pg_catalog.jsonb_array_elements(
        dependents_payload -> 'article_impressions'
      ) AS child
      WHERE child ->> 'article_id'
        IS DISTINCT FROM target_article_id
    ) THEN
      RAISE EXCEPTION
        'publisher delete restore article_impressions rows drifted';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM pg_catalog.jsonb_array_elements(
        dependents_payload -> 'article_reactions'
      ) AS child
      WHERE child ->> 'article_id'
        IS DISTINCT FROM target_article_id
    ) THEN
      RAISE EXCEPTION
        'publisher delete restore article_reactions rows drifted';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM pg_catalog.jsonb_array_elements(
        dependents_payload -> 'article_relations'
      ) AS child
      WHERE child ->> 'source_id'
              IS DISTINCT FROM target_article_id
        AND child ->> 'target_id'
              IS DISTINCT FROM target_article_id
    ) THEN
      RAISE EXCEPTION
        'publisher delete restore article_relations rows drifted';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM pg_catalog.jsonb_array_elements(
        dependents_payload -> 'article_tags'
      ) AS child
      WHERE child ->> 'article_id'
        IS DISTINCT FROM target_article_id
    ) THEN
      RAISE EXCEPTION
        'publisher delete restore article_tags rows drifted';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM pg_catalog.jsonb_array_elements(
        dependents_payload -> 'comments'
      ) AS child
      WHERE child ->> 'article_id'
        IS DISTINCT FROM target_article_id
    ) THEN
      RAISE EXCEPTION
        'publisher delete restore comments rows drifted';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM pg_catalog.jsonb_array_elements(
        dependents_payload -> 'question_articles'
      ) AS child
      WHERE child ->> 'article_id'
        IS DISTINCT FROM target_article_id
    ) THEN
      RAISE EXCEPTION
        'publisher delete restore question_articles rows drifted';
    END IF;
  END LOOP;

  RETURN public.volpred_restore_publisher_article_delete_batch_v1(
    p_expected_candidates
  );
END;
$$;

COMMENT ON FUNCTION
  public.volpred_restore_publisher_article_delete_batch(jsonb)
IS
  'Validate child identity then atomically restore one exact recovery batch.';
COMMENT ON FUNCTION
  public.volpred_restore_publisher_article_delete_batch_v1(jsonb)
IS
  'Internal atomic restore core; callable only by its no-login owner.';

RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION
  public.volpred_restore_publisher_article_delete_batch(jsonb)
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION
  public.volpred_restore_publisher_article_delete_batch(jsonb)
TO service_role;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
