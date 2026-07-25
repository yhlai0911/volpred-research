-- Preserve the original compare-delete transaction boundary while returning
-- typed, service-role-only exception context.  PL/pgSQL's inner exception
-- block rolls back any partial mutation before the diagnostic envelope is
-- returned.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
SET ROLE volpred_ops_definer;

CREATE OR REPLACE FUNCTION
  public.volpred_execute_publisher_article_compare_delete(
    p_owner_generation bigint,
    p_effect_id text,
    p_attempt_count integer,
    p_worker_id text,
    p_primary_authority_key text,
    p_primary_authority_holder_ref text,
    p_primary_authority_epoch bigint,
    p_primary_fencing_token text,
    p_authorization jsonb,
    p_expected_candidate jsonb
  )
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  result jsonb;
  error_sqlstate text;
  error_message text;
  error_detail text;
  error_hint text;
  error_context text;
BEGIN
  BEGIN
    result := public.volpred_compare_delete_publisher_article(
      p_owner_generation,
      p_effect_id,
      p_attempt_count,
      p_worker_id,
      p_primary_authority_key,
      p_primary_authority_holder_ref,
      p_primary_authority_epoch,
      p_primary_fencing_token,
      p_authorization,
      p_expected_candidate
    );
    RETURN jsonb_build_object(
      'schema_version',
        'publisher-article-compare-delete-execution.v1',
      'ok', true,
      'result', result,
      'error', NULL
    );
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS
      error_sqlstate = RETURNED_SQLSTATE,
      error_message = MESSAGE_TEXT,
      error_detail = PG_EXCEPTION_DETAIL,
      error_hint = PG_EXCEPTION_HINT,
      error_context = PG_EXCEPTION_CONTEXT;
    RETURN jsonb_build_object(
      'schema_version',
        'publisher-article-compare-delete-execution.v1',
      'ok', false,
      'result', NULL,
      'error', jsonb_build_object(
        'sqlstate', error_sqlstate,
        'message', error_message,
        'detail', error_detail,
        'hint', error_hint,
        'context', error_context
      )
    );
  END;
END;
$$;

ALTER FUNCTION
  public.volpred_execute_publisher_article_compare_delete(
    bigint, text, integer, text, text, text, bigint, text, jsonb, jsonb
  )
OWNER TO volpred_ops_definer;

REVOKE ALL ON FUNCTION
  public.volpred_execute_publisher_article_compare_delete(
    bigint, text, integer, text, text, text, bigint, text, jsonb, jsonb
  )
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
  public.volpred_execute_publisher_article_compare_delete(
    bigint, text, integer, text, text, text, bigint, text, jsonb, jsonb
  )
TO service_role;

RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
