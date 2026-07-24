-- Make the live owned-email transaction consume the host keepalive lease.
--
-- The original ownership transaction acquired and released
-- notification:email.ops_alert inside each delivery.  That bypassed the
-- process-level HostAuthorityKeepalive enable gate.  Preserve the public RPC
-- signature while changing its authority contract:
--   * begin requires an already-held, unexpired lease for the worker;
--   * authorize_effect_write verifies the raw fencing token;
--   * settle leaves release to the host keepalive lifecycle owner.
--
-- Rewriting the existing definitions keeps this forward migration small and
-- preserves their owner/ACL.  Both replacements fail closed if the preceding
-- canonical migration does not have the expected function bodies.

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
      'public.volpred_begin_owned_email_notification(bigint,text,text,integer,text,text,text)'
    )
  )
  INTO STRICT function_definition;

  rewritten_definition := pg_catalog.replace(
    function_definition,
    $old_begin$
  SELECT * INTO STRICT primary_lease
  FROM volpred_ops.acquire_primary_authority(
    'notification:email.ops_alert',
    btrim(p_worker_id),
    p_lease_seconds,
    p_primary_fencing_token
  );
$old_begin$,
    $new_begin$
  SELECT * INTO STRICT primary_lease
  FROM volpred_ops.primary_authority_lease_reads AS active_lease
  WHERE active_lease.authority_key = 'notification:email.ops_alert'
    AND active_lease.holder_ref = btrim(p_worker_id)
    AND active_lease.lease_expires_at > event_at;
$new_begin$
  );
  IF rewritten_definition = function_definition THEN
    IF pg_catalog.strpos(
      function_definition,
      'FROM volpred_ops.primary_authority_lease_reads'
    ) = 0 THEN
      RAISE EXCEPTION
        'owned email begin authority pre-image did not match';
    END IF;
  ELSE
    EXECUTE rewritten_definition;
  END IF;

  SELECT pg_catalog.pg_get_functiondef(
    pg_catalog.to_regprocedure(
      'public.volpred_settle_owned_email_notification(bigint,text,integer,text,text,bigint,integer,text,text,text,text,bigint,text,text,text,text,text,text,text,text,text,text)'
    )
  )
  INTO STRICT function_definition;

  rewritten_definition := pg_catalog.replace(
    function_definition,
    $old_settle$
  SELECT * INTO STRICT released_authority
  FROM volpred_ops.release_primary_authority(
    btrim(p_primary_authority_key),
    btrim(p_primary_authority_holder_ref),
    p_primary_authority_epoch,
    p_primary_fencing_token
  );
$old_settle$,
    $new_settle$
  -- The host keepalive owns release.  Settlement only consumes the durable
  -- grant that was bound to this exact authority epoch and effect attempt.
$new_settle$
  );
  IF rewritten_definition = function_definition THEN
    IF pg_catalog.strpos(
      function_definition,
      'FROM volpred_ops.release_primary_authority'
    ) > 0 THEN
      RAISE EXCEPTION
        'owned email settlement authority pre-image did not match';
    END IF;
  ELSE
    EXECUTE rewritten_definition;
  END IF;
END;
$migration$;

COMMENT ON FUNCTION public.volpred_begin_owned_email_notification(
  bigint, text, text, integer, text, text, text
) IS
  'Begin one owned email attempt using an already-active host keepalive lease.';

COMMENT ON FUNCTION public.volpred_settle_owned_email_notification(
  bigint, text, integer, text, text, bigint, integer, text, text,
  text, text, bigint, text, text, text, text, text, text, text, text,
  text, text
) IS
  'Settle an owned email attempt; host keepalive retains authority release ownership.';

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
