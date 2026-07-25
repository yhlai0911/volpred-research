-- Atomic, exact recovery projection for publisher article deletion.
--
-- The caller has already verified the canonical recovery JSONL and rechecked
-- its local mutation authority.  This RPC is the only database mutation seam:
-- it validates the live seven-edge cascade contract, locks the complete batch,
-- rejects any state other than absent-or-exact, and restores every parent and
-- child row in one PostgreSQL transaction.  Any exception therefore rolls the
-- whole batch back.  Exact replay performs no writes.
--
-- The function is exposed only because the runtime has a Supabase service-role
-- key and no direct Postgres DSN.  The no-login definer owns the function,
-- keeps an empty search_path, and receives only the table privileges and RLS
-- policies required for this projection.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
GRANT SELECT, INSERT, UPDATE ON
  public.articles,
  public.article_impressions,
  public.article_reactions,
  public.article_relations,
  public.article_tags,
  public.comments,
  public.question_articles
TO volpred_ops_definer;

DROP POLICY IF EXISTS publisher_delete_restore_definer_update
  ON public.articles;
CREATE POLICY publisher_delete_restore_definer_update
  ON public.articles
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_insert
  ON public.articles;
CREATE POLICY publisher_delete_restore_definer_insert
  ON public.articles
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_insert
  ON public.article_impressions;
CREATE POLICY publisher_delete_restore_definer_insert
  ON public.article_impressions
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_update
  ON public.article_impressions;
CREATE POLICY publisher_delete_restore_definer_update
  ON public.article_impressions
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_insert
  ON public.article_reactions;
CREATE POLICY publisher_delete_restore_definer_insert
  ON public.article_reactions
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_update
  ON public.article_reactions;
CREATE POLICY publisher_delete_restore_definer_update
  ON public.article_reactions
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_insert
  ON public.article_relations;
CREATE POLICY publisher_delete_restore_definer_insert
  ON public.article_relations
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_update
  ON public.article_relations;
CREATE POLICY publisher_delete_restore_definer_update
  ON public.article_relations
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_insert
  ON public.article_tags;
CREATE POLICY publisher_delete_restore_definer_insert
  ON public.article_tags
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_update
  ON public.article_tags;
CREATE POLICY publisher_delete_restore_definer_update
  ON public.article_tags
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_insert
  ON public.comments;
CREATE POLICY publisher_delete_restore_definer_insert
  ON public.comments
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_update
  ON public.comments;
CREATE POLICY publisher_delete_restore_definer_update
  ON public.comments
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_insert
  ON public.question_articles;
CREATE POLICY publisher_delete_restore_definer_insert
  ON public.question_articles
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_restore_definer_update
  ON public.question_articles;
CREATE POLICY publisher_delete_restore_definer_update
  ON public.question_articles
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);

SET ROLE volpred_ops_definer;

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
  article_payload jsonb;
  dependents_payload jsonb;
  child_payload jsonb;
  normalized_payload jsonb;
  observed jsonb;
  target_article_id text;
  candidate_count integer;
  missing_article_ids text[] := ARRAY[]::text[];
  restored_count integer := 0;
BEGIN
  IF jsonb_typeof(p_expected_candidates) <> 'array' THEN
    RAISE EXCEPTION
      'publisher delete restore candidates must be an array';
  END IF;
  candidate_count := jsonb_array_length(p_expected_candidates);
  IF candidate_count <= 0 THEN
    RAISE EXCEPTION
      'publisher delete restore candidates must not be empty';
  END IF;
  IF (
    SELECT count(DISTINCT item -> 'article' ->> 'id')
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
  ) <> candidate_count THEN
    RAISE EXCEPTION
      'publisher delete restore article identities must be unique';
  END IF;

  IF public.volpred_read_article_delete_dependency_contract()
      <> jsonb_build_array(
        jsonb_build_object(
          'table', 'article_impressions',
          'column', 'article_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'article_reactions',
          'column', 'article_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'article_relations',
          'column', 'source_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'article_relations',
          'column', 'target_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'article_tags',
          'column', 'article_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'comments',
          'column', 'article_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'question_articles',
          'column', 'article_id',
          'on_delete', 'cascade'
        )
      ) THEN
    RAISE EXCEPTION
      'publisher delete restore cascade contract drifted';
  END IF;

  -- Validate every JSON row against the current physical table shape before
  -- taking locks or attempting a write.  The round trip detects missing or
  -- unknown columns as well as values that coerce to a different SQL value.
  FOR candidate IN
    SELECT item
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
  LOOP
    IF jsonb_typeof(candidate) <> 'object'
        OR (
          SELECT count(*)
          FROM pg_catalog.jsonb_object_keys(candidate)
        ) <> 2
        OR NOT candidate ?& ARRAY['article', 'dependents'] THEN
      RAISE EXCEPTION
        'publisher delete restore candidate fields drifted';
    END IF;
    article_payload := candidate -> 'article';
    dependents_payload := candidate -> 'dependents';
    target_article_id := article_payload ->> 'id';
    IF jsonb_typeof(article_payload) <> 'object'
        OR target_article_id IS NULL
        OR btrim(target_article_id) = ''
        OR jsonb_typeof(dependents_payload) <> 'object'
        OR (
          SELECT count(*)
          FROM pg_catalog.jsonb_object_keys(dependents_payload)
        ) <> 6
        OR NOT dependents_payload ?& ARRAY[
          'article_impressions',
          'article_reactions',
          'article_relations',
          'article_tags',
          'comments',
          'question_articles'
        ] THEN
      RAISE EXCEPTION
        'publisher delete restore candidate schema drifted';
    END IF;

    SELECT to_jsonb(parsed)
    INTO STRICT normalized_payload
    FROM pg_catalog.jsonb_populate_record(
      NULL::public.articles,
      article_payload
    ) AS parsed;
    IF normalized_payload IS DISTINCT FROM article_payload
        OR normalized_payload ->> 'id' <> target_article_id THEN
      RAISE EXCEPTION
        'publisher delete restore article row shape drifted';
    END IF;

    child_payload := dependents_payload -> 'article_impressions';
    IF jsonb_typeof(child_payload) <> 'array'
        OR EXISTS (
          SELECT 1
          FROM pg_catalog.jsonb_array_elements(child_payload) AS item
          CROSS JOIN LATERAL pg_catalog.jsonb_populate_record(
            NULL::public.article_impressions,
            item
          ) AS parsed
          WHERE to_jsonb(parsed) IS DISTINCT FROM item
             OR parsed.article_id::text <> target_article_id
        ) THEN
      RAISE EXCEPTION
        'publisher delete restore article_impressions rows drifted';
    END IF;

    child_payload := dependents_payload -> 'article_reactions';
    IF jsonb_typeof(child_payload) <> 'array'
        OR EXISTS (
          SELECT 1
          FROM pg_catalog.jsonb_array_elements(child_payload) AS item
          CROSS JOIN LATERAL pg_catalog.jsonb_populate_record(
            NULL::public.article_reactions,
            item
          ) AS parsed
          WHERE to_jsonb(parsed) IS DISTINCT FROM item
             OR parsed.article_id::text <> target_article_id
        ) THEN
      RAISE EXCEPTION
        'publisher delete restore article_reactions rows drifted';
    END IF;

    child_payload := dependents_payload -> 'article_relations';
    IF jsonb_typeof(child_payload) <> 'array'
        OR EXISTS (
          SELECT 1
          FROM pg_catalog.jsonb_array_elements(child_payload) AS item
          CROSS JOIN LATERAL pg_catalog.jsonb_populate_record(
            NULL::public.article_relations,
            item
          ) AS parsed
          WHERE to_jsonb(parsed) IS DISTINCT FROM item
             OR target_article_id NOT IN (
               parsed.source_id::text,
               parsed.target_id::text
             )
        ) THEN
      RAISE EXCEPTION
        'publisher delete restore article_relations rows drifted';
    END IF;

    child_payload := dependents_payload -> 'article_tags';
    IF jsonb_typeof(child_payload) <> 'array'
        OR EXISTS (
          SELECT 1
          FROM pg_catalog.jsonb_array_elements(child_payload) AS item
          CROSS JOIN LATERAL pg_catalog.jsonb_populate_record(
            NULL::public.article_tags,
            item
          ) AS parsed
          WHERE to_jsonb(parsed) IS DISTINCT FROM item
             OR parsed.article_id::text <> target_article_id
        ) THEN
      RAISE EXCEPTION
        'publisher delete restore article_tags rows drifted';
    END IF;

    child_payload := dependents_payload -> 'comments';
    IF jsonb_typeof(child_payload) <> 'array'
        OR EXISTS (
          SELECT 1
          FROM pg_catalog.jsonb_array_elements(child_payload) AS item
          CROSS JOIN LATERAL pg_catalog.jsonb_populate_record(
            NULL::public.comments,
            item
          ) AS parsed
          WHERE to_jsonb(parsed) IS DISTINCT FROM item
             OR parsed.article_id::text <> target_article_id
        ) THEN
      RAISE EXCEPTION
        'publisher delete restore comments rows drifted';
    END IF;

    child_payload := dependents_payload -> 'question_articles';
    IF jsonb_typeof(child_payload) <> 'array'
        OR EXISTS (
          SELECT 1
          FROM pg_catalog.jsonb_array_elements(child_payload) AS item
          CROSS JOIN LATERAL pg_catalog.jsonb_populate_record(
            NULL::public.question_articles,
            item
          ) AS parsed
          WHERE to_jsonb(parsed) IS DISTINCT FROM item
             OR parsed.article_id::text <> target_article_id
        ) THEN
      RAISE EXCEPTION
        'publisher delete restore question_articles rows drifted';
    END IF;
  END LOOP;

  -- Lock the complete parent/child scope in a stable order.  All candidate
  -- preflight below happens after these locks and before the first insert.
  PERFORM 1
  FROM public.articles AS row_value
  WHERE row_value.id::text IN (
    SELECT item -> 'article' ->> 'id'
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
  )
  ORDER BY row_value.id
  FOR UPDATE;
  PERFORM 1
  FROM public.article_impressions AS row_value
  WHERE row_value.article_id::text IN (
    SELECT item -> 'article' ->> 'id'
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
  )
  ORDER BY row_value.id
  FOR UPDATE;
  PERFORM 1
  FROM public.article_reactions AS row_value
  WHERE row_value.article_id::text IN (
    SELECT item -> 'article' ->> 'id'
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
  )
  ORDER BY row_value.article_id, row_value.user_id, row_value.reaction
  FOR UPDATE;
  PERFORM 1
  FROM public.article_relations AS row_value
  WHERE row_value.source_id::text IN (
      SELECT item -> 'article' ->> 'id'
      FROM pg_catalog.jsonb_array_elements(
        p_expected_candidates
      ) AS item
    )
     OR row_value.target_id::text IN (
      SELECT item -> 'article' ->> 'id'
      FROM pg_catalog.jsonb_array_elements(
        p_expected_candidates
      ) AS item
    )
  ORDER BY row_value.source_id, row_value.target_id
  FOR UPDATE;
  PERFORM 1
  FROM public.article_tags AS row_value
  WHERE row_value.article_id::text IN (
    SELECT item -> 'article' ->> 'id'
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
  )
  ORDER BY row_value.article_id, row_value.tag_id
  FOR UPDATE;
  PERFORM 1
  FROM public.comments AS row_value
  WHERE row_value.article_id::text IN (
    SELECT item -> 'article' ->> 'id'
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
  )
  ORDER BY row_value.id
  FOR UPDATE;
  PERFORM 1
  FROM public.question_articles AS row_value
  WHERE row_value.article_id::text IN (
    SELECT item -> 'article' ->> 'id'
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
  )
  ORDER BY row_value.question_id, row_value.article_id
  FOR UPDATE;

  FOR candidate IN
    SELECT item
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
    ORDER BY item -> 'article' ->> 'id'
  LOOP
    target_article_id := candidate -> 'article' ->> 'id';
    observed :=
      volpred_ops.read_publisher_article_delete_candidate(
        target_article_id
      );
    IF observed IS NULL THEN
      missing_article_ids :=
        pg_catalog.array_append(
          missing_article_ids,
          target_article_id
        );
      CONTINUE;
    END IF;
    IF observed IS DISTINCT FROM candidate THEN
      RAISE EXCEPTION
        'publisher delete restore scope drifted for article %',
        target_article_id;
    END IF;
  END LOOP;

  restored_count := COALESCE(
    pg_catalog.array_length(missing_article_ids, 1),
    0
  );
  IF restored_count > 0 THEN
    INSERT INTO public.articles
    SELECT parsed.*
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
    CROSS JOIN LATERAL pg_catalog.jsonb_populate_record(
      NULL::public.articles,
      item -> 'article'
    ) AS parsed
    WHERE item -> 'article' ->> 'id' = ANY(missing_article_ids);

    INSERT INTO public.article_impressions
    SELECT parsed.*
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
    CROSS JOIN LATERAL pg_catalog.jsonb_populate_recordset(
      NULL::public.article_impressions,
      item -> 'dependents' -> 'article_impressions'
    ) AS parsed
    WHERE item -> 'article' ->> 'id' = ANY(missing_article_ids);

    INSERT INTO public.article_reactions
    SELECT parsed.*
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
    CROSS JOIN LATERAL pg_catalog.jsonb_populate_recordset(
      NULL::public.article_reactions,
      item -> 'dependents' -> 'article_reactions'
    ) AS parsed
    WHERE item -> 'article' ->> 'id' = ANY(missing_article_ids);

    INSERT INTO public.article_relations
    SELECT DISTINCT ON (parsed.source_id, parsed.target_id) parsed.*
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
    CROSS JOIN LATERAL pg_catalog.jsonb_populate_recordset(
      NULL::public.article_relations,
      item -> 'dependents' -> 'article_relations'
    ) AS parsed
    WHERE item -> 'article' ->> 'id' = ANY(missing_article_ids)
    ORDER BY parsed.source_id, parsed.target_id;

    INSERT INTO public.article_tags
    SELECT parsed.*
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
    CROSS JOIN LATERAL pg_catalog.jsonb_populate_recordset(
      NULL::public.article_tags,
      item -> 'dependents' -> 'article_tags'
    ) AS parsed
    WHERE item -> 'article' ->> 'id' = ANY(missing_article_ids);

    INSERT INTO public.comments
    SELECT parsed.*
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
    CROSS JOIN LATERAL pg_catalog.jsonb_populate_recordset(
      NULL::public.comments,
      item -> 'dependents' -> 'comments'
    ) AS parsed
    WHERE item -> 'article' ->> 'id' = ANY(missing_article_ids);

    INSERT INTO public.question_articles
    SELECT parsed.*
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
    CROSS JOIN LATERAL pg_catalog.jsonb_populate_recordset(
      NULL::public.question_articles,
      item -> 'dependents' -> 'question_articles'
    ) AS parsed
    WHERE item -> 'article' ->> 'id' = ANY(missing_article_ids);
  END IF;

  FOR candidate IN
    SELECT item
    FROM pg_catalog.jsonb_array_elements(
      p_expected_candidates
    ) AS item
  LOOP
    target_article_id := candidate -> 'article' ->> 'id';
    observed :=
      volpred_ops.read_publisher_article_delete_candidate(
        target_article_id
      );
    IF observed IS DISTINCT FROM candidate THEN
      RAISE EXCEPTION
        'publisher delete restore exact read-back failed for article %',
        target_article_id;
    END IF;
  END LOOP;

  RETURN jsonb_build_object(
    'schema_version', 'publisher-article-delete-restore-batch.v1',
    'candidate_count', candidate_count,
    'restored_count', restored_count,
    'restored', true
  );
END;
$$;

COMMENT ON FUNCTION
  public.volpred_restore_publisher_article_delete_batch(jsonb)
IS
  'Atomically restore one exact six-table publisher delete recovery batch.';

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
