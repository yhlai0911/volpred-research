-- Forward-only hardening for the stale publisher-delete reconciliation seam.
-- Every selected lifecycle row must belong to the same immutable request
-- chain; independent foreign keys do not prove these cross-table identities.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
SET ROLE volpred_ops_definer;

DO $migration$
DECLARE
  function_definition text;
  rewritten_definition text;
BEGIN
  SELECT pg_catalog.pg_get_functiondef(
    'public.volpred_reconcile_stale_owned_publisher_article_delete(integer,text)'::regprocedure
  )
  INTO STRICT function_definition;

  rewritten_definition := pg_catalog.replace(
    function_definition,
    $old_selector$AND owned_request.owner_generation = attempt.owner_generation$old_selector$,
    $new_selector$AND owned_request.owner_generation = attempt.owner_generation
      AND owned_request.work_id = attempt.work_id
      AND owned_request.request_sha256 = effect.request_sha256
      AND effect.work_item_id = attempt.work_id
      AND message.effect_id = attempt.effect_id
      AND attempt_receipt.outbox_sequence = attempt.outbox_sequence
      AND attempt_receipt.worker_id = attempt.worker_id
      AND attempt_receipt.evidence_ref = attempt.evidence_ref
      AND attempt_receipt.evidence_sha256 = attempt.evidence_sha256
      AND attempt.work_status = work.status
      AND attempt.effect_status = effect.status
$new_selector$
  );

  IF rewritten_definition = function_definition THEN
    IF pg_catalog.strpos(
      function_definition,
      'owned_request.work_id = attempt.work_id'
    ) = 0 THEN
      RAISE EXCEPTION
        'publisher delete reconciliation selector pre-image did not match';
    END IF;
  ELSE
    EXECUTE rewritten_definition;
  END IF;
END;
$migration$;

RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
