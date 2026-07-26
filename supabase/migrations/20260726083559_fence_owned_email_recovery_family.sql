-- Keep the owned-email actuator scoped to its exact notification family.
-- Owner generations are monotonic per family and can coincide, so generation
-- equality alone is not an authority boundary.

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
      'public.volpred_recover_expired_owned_email_notification(bigint,text,integer,text,text,text)'
    )
  )
  INTO STRICT function_definition;

  rewritten_definition := pg_catalog.replace(
    function_definition,
    $old_scope$
    AND owned_request.owner_generation = ownership.generation
    AND message.attempt_count = attempt.attempt_count
$old_scope$,
    $new_scope$
    AND owned_request.effect_family = ownership.effect_family
    AND owned_request.owner_generation = ownership.generation
    AND message.attempt_count = attempt.attempt_count
$new_scope$
  );
  IF rewritten_definition = function_definition THEN
    IF pg_catalog.strpos(
      function_definition,
      'owned_request.effect_family = ownership.effect_family'
    ) = 0 THEN
      RAISE EXCEPTION
        'owned email recovery family fence pre-image did not match';
    END IF;
  ELSE
    EXECUTE rewritten_definition;
  END IF;

  SELECT pg_catalog.pg_get_functiondef(
    pg_catalog.to_regprocedure(
      'public.volpred_recover_expired_owned_email_notification(bigint,text,integer,text,text,text)'
    )
  )
  INTO STRICT function_definition;

  rewritten_definition := pg_catalog.replace(
    function_definition,
    $old_kind$
    AND effect.status = 'requested'
    AND (
$old_kind$,
    $new_kind$
    AND effect.status = 'requested'
    AND effect.effect_kind = 'email.notification.send'
    AND (
$new_kind$
  );
  IF rewritten_definition = function_definition THEN
    IF pg_catalog.strpos(
      function_definition,
      'effect.effect_kind = ''email.notification.send'''
    ) = 0 THEN
      RAISE EXCEPTION
        'owned email recovery effect-kind fence pre-image did not match';
    END IF;
  ELSE
    EXECUTE rewritten_definition;
  END IF;
END;
$migration$;

COMMENT ON FUNCTION
  public.volpred_recover_expired_owned_email_notification(
    bigint, text, integer, text, text, text
  )
IS
  'Recover one exact-family expired attempt or due retry through a fenced transaction.';

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
