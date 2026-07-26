-- Return the terminal owned-email receipt from the idempotent request RPC.
--
-- A schedule retry uses the same immutable fire payload and request identity.
-- If the first process lost its response after settlement, the retry must read
-- that receipt instead of trying to begin an already-terminal WorkItem and
-- invoking the mail provider twice.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

DO $migration$
DECLARE
  function_definition text;
  rewritten_definition text;
BEGIN
  SELECT pg_catalog.pg_get_functiondef(
    pg_catalog.to_regprocedure(
      'public.volpred_request_owned_email_notification(bigint,text,text,text,text,jsonb,text)'
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
      'schema_version', 'owned-email-request.v1',
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
        'schema_version', 'owned-email-receipt.v1',
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
      'schema_version', 'owned-email-request.v1',
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
        'owned-email terminal replay request pre-image did not match';
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
        'owned-email terminal replay rewrite was incomplete';
    END IF;
    EXECUTE rewritten_definition;
  END IF;
END;
$migration$;

DO $transfer_fence$
DECLARE
  function_definition text;
  rewritten_definition text;
BEGIN
  SELECT pg_catalog.pg_get_functiondef(
    pg_catalog.to_regprocedure(
      'public.volpred_transfer_notification_owner(text,bigint,text,text,text,bigint)'
    )
  )
  INTO STRICT function_definition;

  rewritten_definition := pg_catalog.replace(
    function_definition,
    $old_transfer_gate$
  IF EXISTS (
    SELECT 1
    FROM volpred_ops.owned_notification_attempts
    WHERE status = 'started'
      AND lease_expires_at > clock_timestamp()
  ) THEN
    RAISE EXCEPTION
      'notification ownership transfer requires zero active attempts';
  END IF;
$old_transfer_gate$,
$new_transfer_gate$
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'primary:notification:email.ops_alert',
      0
    )
  );
  IF EXISTS (
    SELECT 1
    FROM volpred_ops.owned_notification_attempts
    WHERE status = 'started'
      AND lease_expires_at > clock_timestamp()
  ) OR EXISTS (
    SELECT 1
    FROM volpred_ops.primary_authority_leases
    WHERE authority_key = 'notification:email.ops_alert'
      AND holder_ref IS NOT NULL
      AND lease_expires_at > clock_timestamp()
  ) THEN
    RAISE EXCEPTION
      'notification ownership transfer requires zero active delivery fences';
  END IF;
$new_transfer_gate$
  );

  IF rewritten_definition = function_definition THEN
    IF pg_catalog.strpos(
      function_definition,
      'notification ownership transfer requires zero active delivery fences'
    ) = 0
        OR pg_catalog.strpos(
          function_definition,
          'primary_authority_leases'
        ) = 0
        OR pg_catalog.strpos(
          function_definition,
          'primary:notification:email.ops_alert'
        ) = 0 THEN
      RAISE EXCEPTION
        'notification ownership transfer fence pre-image did not match';
    END IF;
  ELSE
    IF pg_catalog.strpos(
      rewritten_definition,
      'notification ownership transfer requires zero active delivery fences'
    ) = 0
        OR pg_catalog.strpos(
          rewritten_definition,
          'primary_authority_leases'
        ) = 0
        OR pg_catalog.strpos(
          rewritten_definition,
          'primary:notification:email.ops_alert'
        ) = 0 THEN
      RAISE EXCEPTION
        'notification ownership transfer fence rewrite was incomplete';
    END IF;
    EXECUTE rewritten_definition;
  END IF;
END;
$transfer_fence$;

CREATE OR REPLACE FUNCTION public.volpred_read_owned_email_request(
  p_idempotency_key text
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  existing volpred_ops.owned_notification_requests;
  work volpred_ops.work_item_reads;
  effect volpred_ops.effect_request_reads;
  terminal_attempt volpred_ops.owned_notification_attempts;
  payload_bytes bytea;
  payload_json jsonb;
  terminal_receipt jsonb;
  level text;
  recipient text;
BEGIN
  IF p_idempotency_key IS NULL
      OR pg_catalog.btrim(p_idempotency_key) = '' THEN
    RAISE EXCEPTION 'owned email idempotency_key is required';
  END IF;

  SELECT * INTO existing
  FROM volpred_ops.owned_notification_requests AS owned
  WHERE owned.idempotency_key = pg_catalog.btrim(p_idempotency_key);
  IF existing.idempotency_key IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT * INTO STRICT work
  FROM volpred_ops.work_item_reads AS item
  WHERE item.id = existing.work_id;
  SELECT * INTO STRICT effect
  FROM volpred_ops.effect_request_reads AS requested
  WHERE requested.id = existing.effect_id;
  payload_bytes := volpred_ops.read_effect_payload(effect.payload_ref);
  payload_json := pg_catalog.convert_from(payload_bytes, 'UTF8')::jsonb;

  IF existing.effect_family <> 'email.ops_alert'
      OR effect.work_item_id <> work.id
      OR effect.effect_kind <> 'email.notification.send'
      OR effect.target_ref !~ '^email:[^[:space:]@,;]+@[^[:space:]@,;]+$'
      OR effect.request_sha256 <> existing.request_sha256
      OR effect.requester_ref <> existing.actor_ref
      OR work.requester_ref <> existing.actor_ref
      OR work.title <> payload_json ->> 'subject'
      OR pg_catalog.encode(
        pg_catalog.sha256(payload_bytes),
        'hex'
      ) <> effect.payload_sha256
      OR pg_catalog.jsonb_typeof(payload_json) <> 'object'
      OR (
        SELECT pg_catalog.count(*)
        FROM pg_catalog.jsonb_object_keys(payload_json)
      ) <> 4
      OR NOT payload_json ?& ARRAY[
        'schema_version', 'subject', 'text_body', 'html_body'
      ]
      OR payload_json ->> 'schema_version' <> 'email-notification.v1'
      OR coalesce(
        pg_catalog.btrim(payload_json ->> 'subject'),
        ''
      ) = ''
      OR coalesce(
        pg_catalog.btrim(payload_json ->> 'text_body'),
        ''
      ) = ''
      OR (
        payload_json -> 'html_body' <> 'null'::jsonb
        AND pg_catalog.jsonb_typeof(
          payload_json -> 'html_body'
        ) <> 'string'
      ) THEN
    RAISE EXCEPTION
      'owned email durable request is internally inconsistent';
  END IF;

  level := CASE work.priority
    WHEN 1 THEN 'critical'
    WHEN 2 THEN 'warn'
    WHEN 3 THEN 'info'
    ELSE NULL
  END;
  IF level IS NULL THEN
    RAISE EXCEPTION 'owned email durable priority is unsupported';
  END IF;
  recipient := pg_catalog.substring(effect.target_ref, 7);

  SELECT * INTO terminal_attempt
  FROM volpred_ops.owned_notification_attempts AS attempt
  WHERE attempt.effect_id = existing.effect_id
    AND attempt.status IN ('delivered', 'dead_lettered')
  ORDER BY attempt.attempt_count DESC
  LIMIT 1;
  terminal_receipt := NULL;
  IF terminal_attempt.effect_id IS NOT NULL THEN
    terminal_receipt := pg_catalog.jsonb_build_object(
      'schema_version', 'owned-email-receipt.v1',
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

  RETURN pg_catalog.jsonb_build_object(
    'schema_version', 'owned-email-request-read.v1',
    'command', pg_catalog.jsonb_build_object(
      'schema_version', 'owned-email-command.v1',
      'idempotency_key', existing.idempotency_key,
      'level', level,
      'title', payload_json ->> 'subject',
      'recipient', recipient,
      'text_body', payload_json ->> 'text_body',
      'html_body', payload_json -> 'html_body',
      'actor_ref', existing.actor_ref
    ),
    'request', pg_catalog.jsonb_build_object(
      'schema_version', 'owned-email-request.v1',
      'owner_generation', existing.owner_generation,
      'work_id', existing.work_id,
      'effect_id', existing.effect_id,
      'request_sha256', existing.request_sha256,
      'receipt', terminal_receipt
    )
  );
END;
$$;

COMMENT ON FUNCTION
  public.volpred_request_owned_email_notification(
    bigint, text, text, text, text, jsonb, text
  )
IS
  'Atomically create owned-email work/effect or return its terminal receipt.';

COMMENT ON FUNCTION
  public.volpred_read_owned_email_request(text)
IS
  'Read one immutable owned-email command and optional terminal receipt.';

ALTER FUNCTION public.volpred_read_owned_email_request(text)
  OWNER TO volpred_ops_definer;

REVOKE ALL ON FUNCTION
  public.volpred_read_owned_email_request(text)
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
  public.volpred_read_owned_email_request(text)
TO service_role;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
