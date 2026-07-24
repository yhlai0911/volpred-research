-- Recover an owned publisher delivery when the successful RPC response is lost.
--
-- The request idempotency key already resolves to one durable WorkItem and
-- EffectRequest.  Return its terminal attempt receipt from the same request
-- RPC so a caller retry does not try to begin an already-succeeded WorkItem or
-- invoke the external provider twice.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

DO $migration$
DECLARE
  function_definition text;
  rewritten_definition text;
BEGIN
  SELECT pg_catalog.pg_get_functiondef(
    pg_catalog.to_regprocedure(
      'public.volpred_request_owned_publisher_article_sync(bigint,text,jsonb,text)'
    )
  )
  INTO STRICT function_definition;

  rewritten_definition := pg_catalog.replace(
    function_definition,
    $old_declaration$
  existing volpred_ops.owned_notification_requests;
  work volpred_ops.work_item_reads;
$old_declaration$,
    $new_declaration$
  existing volpred_ops.owned_notification_requests;
  terminal_attempt volpred_ops.owned_notification_attempts;
  terminal_receipt jsonb;
  work volpred_ops.work_item_reads;
$new_declaration$
  );

  rewritten_definition := pg_catalog.replace(
    rewritten_definition,
    $old_existing_replay$
    RETURN jsonb_build_object(
      'schema_version', 'owned-publisher-article-request.v1',
      'owner_generation', existing.owner_generation,
      'work_id', existing.work_id,
      'effect_id', existing.effect_id,
      'request_sha256', existing.request_sha256
    );
$old_existing_replay$,
    $new_existing_replay$
    SELECT * INTO terminal_attempt
    FROM volpred_ops.owned_notification_attempts AS attempt
    WHERE attempt.effect_id = existing.effect_id
      AND attempt.status IN ('delivered', 'dead_lettered')
    ORDER BY attempt.attempt_count DESC
    LIMIT 1;
    terminal_receipt := NULL;
    IF terminal_attempt.effect_id IS NOT NULL THEN
      terminal_receipt := jsonb_build_object(
        'schema_version', 'owned-publisher-article-receipt.v1',
        'owner_generation', terminal_attempt.owner_generation,
        'work_id', terminal_attempt.work_id,
        'work_status', terminal_attempt.work_status,
        'effect_id', terminal_attempt.effect_id,
        'effect_status', terminal_attempt.effect_status,
        'attempt_count', terminal_attempt.attempt_count,
        'disposition', terminal_attempt.disposition,
        'evidence_ref', terminal_attempt.evidence_ref,
        'evidence_sha256', terminal_attempt.evidence_sha256,
        'primary_authority_ref',
          terminal_attempt.primary_authority_ref,
        'recorded_at', terminal_attempt.finished_at
      );
    END IF;
    RETURN jsonb_build_object(
      'schema_version', 'owned-publisher-article-request.v1',
      'owner_generation', existing.owner_generation,
      'work_id', existing.work_id,
      'effect_id', existing.effect_id,
      'request_sha256', existing.request_sha256,
      'receipt', terminal_receipt
    );
$new_existing_replay$
  );

  rewritten_definition := pg_catalog.replace(
    rewritten_definition,
    $old_new_request$
    'work_id', work.id,
    'effect_id', effect.id,
    'request_sha256', request_sha256
  );
$old_new_request$,
    $new_new_request$
    'work_id', work.id,
    'effect_id', effect.id,
    'request_sha256', request_sha256,
    'receipt', NULL
  );
$new_new_request$
  );

  IF rewritten_definition = function_definition THEN
    IF pg_catalog.strpos(
      function_definition,
      'terminal_attempt volpred_ops.owned_notification_attempts'
    ) = 0
        OR pg_catalog.strpos(
          function_definition,
          '''receipt'', terminal_receipt'
        ) = 0
        OR pg_catalog.strpos(
          function_definition,
          '''receipt'', NULL'
        ) = 0 THEN
      RAISE EXCEPTION
        'publisher terminal replay request pre-image did not match';
    END IF;
  ELSE
    IF pg_catalog.strpos(
      rewritten_definition,
      'terminal_attempt volpred_ops.owned_notification_attempts'
    ) = 0
        OR pg_catalog.strpos(
          rewritten_definition,
          '''receipt'', terminal_receipt'
        ) = 0
        OR pg_catalog.strpos(
          rewritten_definition,
          '''receipt'', NULL'
        ) = 0 THEN
      RAISE EXCEPTION
        'publisher terminal replay rewrite was incomplete';
    END IF;
    EXECUTE rewritten_definition;
  END IF;
END;
$migration$;

COMMENT ON FUNCTION
  public.volpred_request_owned_publisher_article_sync(
    bigint, text, jsonb, text
  )
IS
  'Atomically create publisher work/effect or return its terminal receipt.';

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
